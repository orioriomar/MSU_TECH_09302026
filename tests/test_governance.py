"""Tests for the rules a judge will poke at: unknown is never called wrong, one ticket per wrong
fact, a fix only counts when a re-check proves it, and a failed AI call never becomes a score.
"""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app, ai, scoring, evals
from verifier import verify, normalize

FACTS = [
    {'fact_id': 'F1', 'approved': 1, 'product_id': 'mofongo', 'product_name': 'Mofongo', 'field': 'price_usd',
     'value': '14.00', 'context': 'lunch', 'source_url': 'https://x.example/menu'},
    {'fact_id': 'F2', 'approved': 1, 'product_id': 'mofongo', 'product_name': 'Mofongo', 'field': 'price_usd',
     'value': '18.00', 'context': 'dinner', 'source_url': 'https://x.example/menu'},
    {'fact_id': 'F3', 'approved': 1, 'product_id': 'business', 'product_name': 'Cafe', 'field': 'address',
     'value': '118 Market St, Paterson, NJ 07505', 'context': '', 'source_url': 'https://x.example/visit'},
    {'fact_id': 'F4', 'approved': 1, 'product_id': 'business', 'product_name': 'Cafe', 'field': 'policy',
     'value': 'no pets inside', 'context': 'pets', 'source_url': 'https://x.example/faq'},
    {'fact_id': 'F5', 'approved': 0, 'product_id': 'flan', 'product_name': 'Flan', 'field': 'price_usd',
     'value': '5.00', 'context': '', 'source_url': ''},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'DB', tmp_path / 'gov.sqlite3')
    app.init_db()
    return TestClient(app.app)


def claim(**kw):
    return {'product_id': 'mofongo', 'field': 'price_usd', 'value': '14', 'context': 'lunch', **kw}


# ---------------------------------------------------------------- verifier: what counts as wrong
def test_correct_incorrect_ambiguous_unverifiable():
    assert verify(claim(value='$14'), FACTS)['verdict'] == 'CORRECT'
    assert verify(claim(value='18'), FACTS)['verdict'] == 'INCORRECT'
    assert verify(claim(context=''), FACTS)['verdict'] == 'NEEDS_REVIEW'          # lunch or dinner?
    assert verify(claim(product_id='tostones'), FACTS)['verdict'] == 'UNVERIFIABLE'
    assert verify(claim(product_id='flan', context=''), FACTS)['verdict'] == 'UNVERIFIABLE'  # draft fact is not truth


def test_price_normalization():
    assert normalize('price_usd', '$14') == normalize('price_usd', '14.00') == '14.00'
    assert normalize('price_usd', '14 dollars') == '14.00'
    assert normalize('price_usd', '$1,200') == '1200.00'
    assert normalize('price_usd', '$14-16') is None          # a range is ambiguous -> review
    assert normalize('price_usd', 'about 14 or 15') is None
    assert normalize('price_usd', 'cheap') is None


def test_availability_normalization():
    assert normalize('availability', 'In stock') == 'available'
    assert normalize('availability', 'not on the menu') == 'unavailable'
    assert normalize('availability', 'permanently closed') == 'unavailable'
    assert normalize('availability', 'temporarily closed') is None   # unclear -> review, never "wrong"


def test_address_without_zip_is_not_called_wrong():
    ok = {'product_id': 'business', 'field': 'address', 'context': ''}
    assert verify({**ok, 'value': '118 Market Street, Paterson'}, FACTS)['verdict'] == 'CORRECT'
    assert verify({**ok, 'value': '118 Market St, Paterson, NJ 07501'}, FACTS)['verdict'] == 'INCORRECT'
    assert verify({**ok, 'value': '42 Main St, Paterson, NJ 07505'}, FACTS)['verdict'] == 'INCORRECT'


def test_unrecognized_policy_wording_goes_to_review_not_wrong():
    p = {'product_id': 'business', 'field': 'policy', 'context': 'pets'}
    assert verify({**p, 'value': 'no pets inside'}, FACTS)['verdict'] == 'CORRECT'
    assert verify({**p, 'value': 'dogs are not allowed indoors'}, FACTS)['verdict'] == 'NEEDS_REVIEW'


# ---------------------------------------------------------------- extractor guardrails
def test_extractor_invented_product_or_quote_is_rejected(monkeypatch):
    facts = [{**f, 'approved': 1} for f in FACTS[:2]]
    monkeypatch.setattr(ai, 'call_ai', lambda *a: {'brand_mentioned': True, 'claims': [
        {'product_id': 'lobster', 'field': 'price_usd', 'value': '30', 'context': '', 'quote': 'lobster is $30'}]})
    with pytest.raises(ai.AIError, match='unknown product'):
        ai.extract_claims('The lobster is $30.', {'text': 'q'}, 'Cafe', facts)
    monkeypatch.setattr(ai, 'call_ai', lambda *a: {'brand_mentioned': True, 'claims': [
        {'product_id': 'mofongo', 'field': 'price_usd', 'value': '18', 'context': 'lunch', 'quote': 'mofongo is $18'}]})
    with pytest.raises(ai.AIError, match='quote'):
        ai.extract_claims('Mofongo costs fourteen dollars.', {'text': 'q'}, 'Cafe', facts)


# ---------------------------------------------------------------- scoring
def test_hallucination_classification_unknown_is_not_made_up():
    safe = {'type': 'stress', 'abstained': True, 'claims': [{'verdict': 'INCORRECT', 'field': 'policy'}]}
    unknown = {'type': 'stress', 'claims': [{'verdict': 'UNVERIFIABLE', 'field': 'price_usd'}]}
    review = {'type': 'stress', 'claims': [{'verdict': 'NEEDS_REVIEW', 'field': 'price_usd'}]}
    wrong = {'type': 'stress', 'claims': [{'verdict': 'INCORRECT', 'field': 'policy'}]}
    yes = {'type': 'stress', 'claims': [], 'unsupported': True}
    assert [scoring.is_hallucination(r) for r in (safe, unknown, review, wrong, yes)] == [False, False, False, True, True]


def test_failed_ai_calls_never_count_as_a_score():
    results = [{'type': 'visibility', 'error': 'Gemini quota reached.'} for _ in range(5)] + \
              [{'type': 'stress', 'error': 'Gemini quota reached.', 'claims': []}]
    card = scoring.scorecard(results)
    assert card['health'] is None and card['visibility']['score'] is None and card['hallucination']['rate'] is None
    assert card['errors'] == 6 and card['answered'] == 0
    mixed = results + [{'type': 'visibility', 'visibility': {'mentioned': True, 'rank': 1, 'framing': 'recommended'}}]
    assert scoring.scorecard(mixed)['visibility'] == {'score': 100.0, 'inclusion_rate': 100.0, 'questions': 1, 'mentioned': 1}


def test_visibility_ranking_list_and_prose():
    listed = evals.parse_visibility('1. Isla Kitchen\n2. Borinquen Grill\n3. Casa Coquí Café', 'Casa Coquí Café')
    assert listed['rank'] == 3 and listed['framing'] == 'neutral'
    prose = evals.parse_visibility('For Puerto Rican food in North Jersey, I recommend Casa Coqui Cafe.',
                                   'Casa Coquí Café', 'Where can I get Puerto Rican food in North Jersey?')
    assert prose == {'mentioned': True, 'rank': 1, 'framing': 'recommended'}
    neg = evals.parse_visibility('Casa Coquí Café has mixed reviews lately.', 'Casa Coquí Café')
    assert neg['framing'] == 'negative' and scoring.visibility_points(neg) == pytest.approx(0.2)


# ---------------------------------------------------------------- ticket lifecycle (API)
def _setup_bistro(client):
    csv_text = ('fact_id,business_id,business_name,product_id,product_name,field,value,context,source_url,checked_at,approved,is_demo\n'
                'B1,bistro_taino,Bistro Taíno,bacalaitos,Bacalaitos,availability,available,,https://bistro.example/menu,2026-09-29,yes,no\n')
    assert client.post('/api/catalog/import', json={'csv_text': csv_text}).status_code == 200
    qid = client.post('/api/questions', json={'business_id': 'bistro_taino', 'type': 'accuracy',
                      'text': 'Does Bistro Taíno serve bacalaitos?', 'product_id': 'bacalaitos',
                      'target_field': 'availability'}).json()['id']
    return qid


def _answer(client, qid, text, value, quote):
    return client.post('/api/answers', json={'question_id': qid, 'answer': text, 'extraction': 'manual',
        'citations': ['https://old-listing.example/menu'],
        'manual_claims': [{'product_id': 'bacalaitos', 'field': 'availability', 'value': value,
                           'context': '', 'quote': quote}]}).json()


def test_correct_claim_creates_no_ticket(client):
    qid = _setup_bistro(client)
    r = _answer(client, qid, 'Yes, Bistro Taíno serves bacalaitos.', 'available', 'serves bacalaitos')
    assert r['claims'][0]['verdict'] == 'CORRECT' and not r['tickets_created']


def test_same_wrong_fact_in_new_words_updates_one_ticket(client):
    qid = _setup_bistro(client)
    first = _answer(client, qid, 'Bistro Taíno does not serve bacalaitos.', 'unavailable', 'does not serve bacalaitos')
    again = _answer(client, qid, "Bacalaitos aren't on the menu at Bistro Taíno.", 'not on the menu', "aren't on the menu")
    assert len(first['tickets_created']) == 1 and not again['tickets_created']
    assert again['tickets_updated'] == first['tickets_created']
    t = client.get('/api/report/bistro_taino').json()['tickets']
    assert len(t) == 1 and t[0]['occurrences'] == 2 and t[0]['evidence_quote'] == 'does not serve bacalaitos'


def test_retest_still_wrong_stays_open_then_passes(client):
    qid = _setup_bistro(client)
    tid = _answer(client, qid, 'Bistro Taíno does not serve bacalaitos.', 'unavailable', 'does not serve bacalaitos')['tickets_created'][0]
    assert client.post(f'/api/tickets/{tid}/decision', json={'action': 'approve'}).json()['status'] == 'approved'
    _answer(client, qid, 'Bistro Taíno does not serve bacalaitos.', 'unavailable', 'does not serve bacalaitos')
    t = client.get('/api/report/bistro_taino').json()['tickets'][0]
    assert t['status'] == 'approved' and t['still_wrong'] is True           # approved is not fixed
    r = _answer(client, qid, 'Yes, Bistro Taíno serves bacalaitos.', 'available', 'serves bacalaitos')
    assert r['tickets_verified_on_retest'] == [tid]
    t = client.get('/api/report/bistro_taino').json()['tickets'][0]
    assert t['status'] == 'verified' and t['still_wrong'] is False


def test_rejected_ticket_is_not_reopened_by_the_same_fact(client):
    qid = _setup_bistro(client)
    tid = _answer(client, qid, 'Bistro Taíno does not serve bacalaitos.', 'unavailable', 'does not serve bacalaitos')['tickets_created'][0]
    assert client.post(f'/api/tickets/{tid}/decision', json={'action': 'reject', 'note': 'seasonal'}).json()['status'] == 'rejected'
    assert client.post(f'/api/tickets/{tid}/decision', json={'action': 'approve'}).status_code == 409
    again = _answer(client, qid, 'Bistro Taíno does not serve bacalaitos.', 'unavailable', 'does not serve bacalaitos')
    assert not again['tickets_created']
    ts = client.get('/api/report/bistro_taino').json()['tickets']
    assert len(ts) == 1 and ts[0]['status'] == 'rejected'
    assert any(a['action'] == 'repeat_after_dismissal' for a in client.get('/api/report/bistro_taino').json()['audit'])


# ---------------------------------------------------------------- live check failure + demo without a key
def test_quota_error_stops_live_check_and_is_not_scored(client, monkeypatch):
    csv_text = (Path(app.BASE) / 'data/business_TEMPLATE.csv').read_text()
    assert client.post('/api/business/setup', json={'csv_text': csv_text}).status_code == 200
    monkeypatch.setenv('GEMINI_API_KEY', 'test')

    def quota(_):
        raise RuntimeError("429 RESOURCE_EXHAUSTED. {'error': {'message': 'secret account detail'}}")
    monkeypatch.setattr(app, 'ask_gemini_shopper', quota)
    start = client.post('/api/evals/start', json={'business_id': 'my_business', 'mode': 'live_gemini'}).json()
    step = client.post(f"/api/evals/{start['id']}/step").json()
    assert step['done'] and step['aborted'] == 'quota' and step['index'] == 1
    assert 'secret' not in step['result']['error'] and 'quota' in step['result']['error'].lower()
    assert client.get('/api/evals?business_id=my_business').json()['runs'] == []   # failed check is never "latest"


def test_demo_works_without_api_key(client, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', '')
    app.seed_showcase('casa_coqui')
    runs = client.get('/api/evals?business_id=casa_coqui').json()['runs']
    assert [r['label'] for r in runs] == ['Week 1 check', 'Week 3 check (after fixes)']
    assert runs[1]['scores']['health'] > runs[0]['scores']['health']
    assert client.get('/').status_code == 200
    d = client.post('/api/geo/draft', json={'business_id': 'casa_coqui', 'finding': {'id': 'GEO-FAQ'}}).json()
    assert d['source'] == 'template' and d['status'] == 'needs_approval'
    assert client.post('/api/evals/extractor', json={}).status_code == 400    # needs a key, says so clearly


def test_unsafe_business_id_is_rejected(client):
    bad = ('fact_id,business_id,business_name,product_id,product_name,field,value,context,source_url,checked_at,approved,is_demo\n'
           "X1,x');alert(1);//,Evil,business,Evil,hours,daily 9-5,,https://e.example,2026-09-29,yes,no\n")
    r = client.post('/api/business/setup', json={'csv_text': bad})
    assert r.status_code == 400 and 'lowercase' in r.json()['detail']
