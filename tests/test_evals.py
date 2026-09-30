import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app, scoring, evals, geo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'DB', tmp_path / 'evals.sqlite3')
    app.init_db()
    return TestClient(app.app)


def test_scoring_formulas_by_hand():
    results = [
        {'type': 'visibility', 'visibility': {'mentioned': True, 'rank': 1, 'framing': 'recommended'}},
        {'type': 'visibility', 'visibility': {'mentioned': True, 'rank': 2, 'framing': 'neutral'}},
        {'type': 'visibility', 'visibility': {'mentioned': False}},
        {'type': 'accuracy', 'claims': [{'field': 'price_usd', 'verdict': 'INCORRECT'},
                                        {'field': 'hours', 'verdict': 'CORRECT'},
                                        {'field': 'policy', 'verdict': 'UNVERIFIABLE'}]},
        {'type': 'stress', 'claims': [], 'unsupported': True},
        {'type': 'stress', 'claims': [], 'abstained': True},
    ]
    card = scoring.scorecard(results)
    assert card['visibility']['score'] == round(100 * (1 + 0.3 + 0) / 3, 1)   # 43.3
    assert card['visibility']['inclusion_rate'] == 66.7
    assert card['accuracy']['score'] == 40.0          # 1 - 3/(3+2); unverifiable ignored
    assert card['hallucination']['rate'] == 50.0
    assert card['health'] == round(0.4 * 40 + 0.35 * 43.3 + 0.25 * 50, 1)


def test_health_needs_accuracy_and_visibility():
    assert scoring.health_score(80, 60, None) == round((0.4 * 80 + 0.35 * 60) / 0.75, 1)   # renormalized
    assert scoring.health_score(None, 0, 0) is None      # "I don't know" everywhere is not a good score
    assert scoring.health_score(80, None, 0) is None


def test_baseline_then_retest_improves_and_keeps_unfixed_ticket_open(client):
    base = client.post('/api/evals/run', json={'business_id': 'casa_coqui', 'mode': 'mock_baseline'}).json()
    assert base['synthetic'] and base['scores']['questions'] == 20
    tickets = client.get('/api/report/casa_coqui').json()['tickets']
    # 7 wrong facts (the DoorDash and "free delivery" answers are the SAME wrong fact -> one ticket)
    # + 1 made-up claim
    assert len(tickets) == 8 and all(t['status'] == 'pending' for t in tickets)
    for t in tickets:
        client.post(f"/api/tickets/{t['id']}/decision", json={'action': 'approve', 'note': 'test'})
    after = client.post('/api/evals/run', json={'business_id': 'casa_coqui', 'mode': 'mock_after'}).json()
    cmp = client.get(f"/api/evals/compare/{base['id']}/{after['id']}").json()
    assert cmp['delta']['health'] > 0 and cmp['delta']['hallucination_rate'] < 0
    ts = client.get('/api/report/casa_coqui').json()['tickets']
    assert any(t['title'] == 'Mofongo: price (lunch) discrepancy' and t['status'] == 'verified' for t in ts)
    # Approved but the AI still repeats it -> ticket stays open, occurrence counted
    doordash = [t for t in ts if t['ai_value'] == 'delivery via doordash'][0]
    assert doordash['status'] == 'approved' and doordash['still_wrong'] is True
    assert doordash['occurrences'] == 4        # Week 1: 2 answers, Week 3: 2 answers, all one ticket
    assert len(ts) == 8                         # no duplicate tickets were opened on the re-check
    bac = [t for t in ts if t['product_id'] == 'bacalaitos'][0]
    assert bac['status'] == 'verified' and bac['evidence_quote']


def test_eval_set_is_locked_no_duplicates(client):
    client.post('/api/evals/run', json={'mode': 'mock_baseline'})
    client.post('/api/evals/run', json={'mode': 'mock_baseline'})
    qs = [q for q in client.get('/api/questions').json() if q['business_id'] == 'casa_coqui']
    assert len(qs) == 20


def test_live_eval_requires_key(client, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    assert client.post('/api/evals/run', json={'mode': 'live_gemini'}).status_code == 400


def test_visibility_parser():
    ans = '1. Borinquen Grill\n2. Casa Coqui Cafe, I recommend it for mofongo\n3. Isla Kitchen'
    v = evals.parse_visibility(ans, 'Casa Coquí Café')
    assert v == {'mentioned': True, 'rank': 2, 'framing': 'recommended'}
    assert evals.parse_visibility('Try Isla Kitchen.', 'Casa Coquí Café')['mentioned'] is False
    assert evals.detect_abstention("I couldn't confirm that; best to call them.")


def test_robots_parser_and_geo_rules():
    robots = 'User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin\n'
    assert geo.robots_blocked_bots(robots) == ['GPTBot']
    prof = evals.load_profile('casa_coqui')
    recs = geo.recommend(prof['signals'], None, [], prof)
    ids = {r['id'] for r in recs}
    assert {'GEO-CRAWL', 'GEO-SCHEMA', 'GEO-MENU', 'ACC-LISTING-HOURS', 'ACC-LISTING-DELIVERY'} <= ids
    assert recs[0]['priority'] == 'high'


def test_extractor_metrics():
    m = evals.extractor_metrics([('a',), ('b',)], [('a',), ('c',)])
    assert (m['precision'], m['recall']) == (50.0, 50.0)


def test_csv_setup_then_live_check_step_by_step(client, monkeypatch):
    """Upload a CSV, build its questions, then run a live check one question at a time
    with Gemini stubbed out: a wrong price must be flagged and turned into a ticket."""
    csv_text = (Path(app.BASE) / 'data/business_TEMPLATE.csv').read_text()
    r = client.post('/api/business/setup', json={'csv_text': csv_text, 'location': 'Paterson, NJ',
                                                  'category': 'restaurant', 'visibility': 2, 'stress': 1})
    assert r.status_code == 200, r.text
    setup = r.json()
    assert setup['business_id'] == 'my_business' and setup['questions'] == 7 + 2 + 1
    assert any(b['business_id'] == 'my_business' for b in client.get('/api/businesses').json()['businesses'])

    import ai
    from models import ClaimBatch
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.setenv('LIVE_EVAL_DELAY', '0')

    def fake_shopper(text):
        if 'Signature Dish' in text:
            return ('At My Business the Signature Dish costs $15.', ['https://oldmenu.example/x'])
        if 'opening hours' in text:
            return ('My Business is open Tuesday through Sunday, 11 AM to 9 PM.', [])
        return ('Try My Business in Paterson, I recommend it.', [])
    monkeypatch.setattr(app, 'ask_gemini_shopper', fake_shopper)

    def fake_extract(answer, q, brand, facts):
        if 'Signature Dish costs $15' in answer:
            return ClaimBatch.model_validate({'brand_mentioned': True, 'claims': [
                {'product_id': 'signature_dish', 'field': 'price_usd', 'value': '15', 'context': '',
                 'quote': 'the Signature Dish costs $15'}]})
        if 'Tuesday through Sunday' in answer:
            return ClaimBatch.model_validate({'brand_mentioned': True, 'claims': [
                {'product_id': 'business', 'field': 'hours', 'value': 'Tuesday through Sunday, 11 AM to 9 PM',
                 'context': '', 'quote': 'open Tuesday through Sunday, 11 AM to 9 PM'}]})
        return ClaimBatch.model_validate({'brand_mentioned': True, 'claims': []})
    monkeypatch.setattr(app, 'extract_claims', fake_extract)

    start = client.post('/api/evals/start', json={'business_id': 'my_business', 'mode': 'live_gemini'}).json()
    flagged, steps = [], None
    for _ in range(start['total']):
        steps = client.post(f"/api/evals/{start['id']}/step").json()
        flagged += [t for t in steps['tickets'] if t['new']]
    assert steps['done'] and steps['scores']['questions'] == start['total']
    assert [t['field'] for t in flagged] == ['price_usd']          # wrong price flagged
    assert flagged[0]['ai_value'] == '15.00' and flagged[0]['verified_value'] == '12.00'
    hours = [r for r in app.get_eval(start['id'])['results'] if 'opening hours' in r['question']][0]
    assert hours['outcome'] == 'CORRECT'                            # different wording, same hours
    assert client.post(f"/api/evals/{start['id']}/step").status_code == 409
    assert client.post('/api/business/my_business/remove').status_code == 200


def test_made_up_trick_answer_is_ticketed_then_fixed(client):
    client.post('/api/evals/run', json={'business_id': 'casa_coqui', 'mode': 'mock_baseline'})
    made_up = [t for t in client.get('/api/report/casa_coqui').json()['tickets'] if t['field'] == 'invented']
    assert len(made_up) == 1 and made_up[0]['priority'] == 'medium' and 'happy hour' in made_up[0]['ai_value']
    client.post(f"/api/tickets/{made_up[0]['id']}/decision", json={'action': 'approve'})
    client.post('/api/evals/run', json={'business_id': 'casa_coqui', 'mode': 'mock_after'})
    t = [t for t in client.get('/api/report/casa_coqui').json()['tickets'] if t['field'] == 'invented'][0]
    assert t['status'] == 'verified'


def test_csv_business_live_check_flags_problems(client, monkeypatch):
    """Upload a CSV, run a live check (Gemini faked), and confirm wrong facts become tickets."""
    import ai
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.setenv('LIVE_EVAL_DELAY', '0')
    csv_text = (Path(app.BASE) / 'data/business_TEMPLATE.csv').read_text()
    def fake_extract(system, prompt, schema):
        if 'requested_counts' in prompt:
            raise ai.AIError('use templates')
        import json as _j
        ans = _j.loads(prompt)['answer']
        if '$15' in ans:
            return {'brand_mentioned': True, 'claims': [{'product_id': 'signature_dish', 'field': 'price_usd',
                    'value': '15', 'context': '', 'quote': 'costs $15'}]}
        return {'brand_mentioned': True, 'claims': []}
    monkeypatch.setattr(ai, 'call_ai', fake_extract)
    monkeypatch.setattr(app, 'ask_gemini_shopper', lambda q: ('The Signature Dish costs $15.', ['https://old.example/menu'])
                        if 'Signature Dish' in q else ("I couldn't confirm that.", []))
    setup = client.post('/api/business/setup', json={'csv_text': csv_text, 'location': 'Paterson, NJ', 'category': 'restaurant'})
    assert setup.status_code == 200 and setup.json()['questions'] >= 7
    start = client.post('/api/evals/start', json={'business_id': 'my_business', 'mode': 'live_gemini'}).json()
    created = []
    for _ in range(start['total']):
        step = client.post(f"/api/evals/{start['id']}/step").json()
        created += [t for t in step['tickets'] if t['event'] == 'created']
    assert step['done'] and step['scores']['accuracy']['incorrect'] == 1
    assert len(created) == 1 and created[0]['ai_value'] == '15.00' and created[0]['verified_value'] == '12.00'


def test_plain_product_list_is_converted(client):
    csv_text = ("SKU,Product Name,Category,Price,Stock Quantity,Description\n"
                "BL-COF-001,Signature Espresso Roast,Coffee,16.99,45,Dark roast (12 oz bag).\n"
                "BL-TEA-102,Jasmine Green Pearls,Tea,22.0,0,Green tea (3 oz tin).\n,,,,,\n")
    no_name = client.post('/api/business/setup', json={'csv_text': csv_text})
    assert no_name.status_code == 400 and 'business name' in no_name.json()['detail']
    r = client.post('/api/business/setup', json={'csv_text': csv_text, 'business_name': 'Bean & Leaf',
                                                 'location': 'Montclair, NJ', 'category': 'coffee shop'}).json()
    assert r['business_id'] == 'bean_leaf' and r['facts'] == 4 and r['synthetic'] is True
    facts = {(f['product_id'], f['field']): f['value'] for f in client.get('/api/facts').json()['facts'] if f['business_id'] == 'bean_leaf'}
    assert facts[('bl_cof_001', 'price_usd')] == '16.99' and facts[('bl_tea_102', 'availability')] == 'unavailable'
