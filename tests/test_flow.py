import csv, io, json, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from models import ClaimBatch
from verifier import verify

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',tmp_path/'isolated.sqlite3')
    app.init_db()
    return TestClient(app.app)

def test_verifier_context_and_missing_fact():
    facts=[{'fact_id':'B3','approved':1,'product_id':'carne_frita','field':'price_usd','value':'15',
            'context':'lunch','source_url':'https://example.com','product_name':'Carne Frita'}]
    assert verify({'product_id':'carne_frita','field':'price_usd','value':'18','context':'lunch'},facts)['verdict']=='INCORRECT'
    assert verify({'product_id':'carne_frita','field':'price_usd','value':'15','context':'lunch'},facts)['verdict']=='CORRECT'
    assert verify({'product_id':'carne_frita','field':'price_usd','value':'18','context':''},facts)['verdict']=='NEEDS_REVIEW'
    assert verify({'product_id':'unknown','field':'price_usd','value':'18','context':'lunch'},facts)['verdict']=='UNVERIFIABLE'

def test_sample_demo_only_and_approval(client):
    r=client.post('/api/demo');assert r.status_code==200
    d=client.get('/api/dashboard').json()
    assert d['metrics']['real_answers']==0
    assert d['metrics']['synthetic_answers']==4
    assert d['metrics']['accuracy_pct'] is None
    assert len(d['tickets'])==1
    t=d['tickets'][0]
    assert t['title']=='Orange Blossom Cookies: availability discrepancy'
    assert t['ai_value']=='unavailable' and t['verified_value']=='available'
    approved=client.post(f'/api/tickets/{t["id"]}/decision',json={'action':'approve','note':'Demo review'})
    assert approved.status_code==200 and approved.json()['status']=='approved'
    assert client.post(f'/api/tickets/{t["id"]}/decision',json={'action':'approve'}).status_code==409
    assert len(client.get('/api/dashboard').json()['audit'])>=1

def test_import_real_business_saved_answer_ticket_dedupe_and_retest(client):
    rows=list(csv.DictReader((Path(app.BASE)/'data/bistro_taino_TEMPLATE.csv').open(encoding='utf-8')))
    for x in rows:
        x['approved']='yes';x['source_url']='https://official.example/menu';x['checked_at']='2026-09-29'
    output=io.StringIO();w=csv.DictWriter(output,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    assert client.post('/api/catalog/import',json={'csv_text':output.getvalue()}).status_code==200
    q=client.post('/api/questions',json={'business_id':'bistro_taino','type':'accuracy',
        'text':'Does Bistro Taíno serve Bacalaitos?','product_id':'bacalaitos','target_field':'availability'})
    assert q.status_code==200; qid=q.json()['id']
    answer='No, Bistro Taíno does not currently serve Bacalaitos.'
    claim={'product_id':'bacalaitos','field':'availability','value':'unavailable','context':'',
           'quote':'does not currently serve Bacalaitos'}
    payload={'question_id':qid,'answer':answer,'extraction':'manual','manual_claims':[claim],
             'citations':['https://some-thirdparty.example/old-menu']}
    r=client.post('/api/answers',json=payload).json()
    assert r['extraction_status']=='complete' and len(r['tickets_created'])==1
    r2=client.post('/api/answers',json=payload).json()
    assert not r2['tickets_created'] and r2['tickets_updated']==r['tickets_created']
    t=client.get('/api/dashboard').json()['tickets'][0]
    assert t['occurrences']==2 and t['status']=='pending'
    assert client.post(f'/api/tickets/{t["id"]}/decision',json={'action':'approve','note':'Reviewed'}).status_code==200
    corrected={**payload,'answer':'Yes, Bistro Taíno serves Bacalaitos.',
               'manual_claims':[{**claim,'value':'available','quote':'serves Bacalaitos'}]}
    retest=client.post('/api/answers',json=corrected).json()
    assert t['id'] in retest['tickets_verified_on_retest']
    d=client.get('/api/dashboard').json()
    assert d['metrics']['real_answers']==3
    assert d['metrics']['accuracy_pct']==33.3
    assert d['tickets'][0]['status']=='verified'

def test_bad_extraction_quote_never_creates_ticket(client):
    payload={'question_id':'A001','answer':'This bakery sells orange cookies.', 'extraction':'manual',
            'manual_claims':[{'product_id':'orange_cookies','field':'availability','value':'unavailable',
                              'context':'','quote':'the store does NOT sell orange cookies'}]}
    r=client.post('/api/answers',json=payload).json()
    assert r['extraction_status']=='failed' and not r['tickets_created']
    assert client.get('/api/dashboard').json()['metrics']['real_answers']==1

def test_unapproved_catalog_not_authoritative(client):
    src=(Path(app.BASE)/'data/bistro_taino_TEMPLATE.csv').read_text()
    r=client.post('/api/catalog/import',json={'csv_text':src})
    assert r.status_code==200
    with app.conn() as c:
        f=app.rows(c,"SELECT * FROM facts WHERE business_id='bistro_taino'")
    assert all(x['approved']==0 for x in f)
    assert verify({'product_id':'bacalaitos','field':'availability','value':'unavailable','context':''},f)['verdict']=='UNVERIFIABLE'

def test_generate_and_formatter_with_stubbed_ollama(client,monkeypatch):
    import ai
    def fake_call(system,prompt,schema):
        if 'requested_counts' in prompt:
            return {'questions':[{'type':'visibility','text':'Where can I buy neighborhood cookies?',
                 'product_id':'','target_field':'','context':''},
                 {'type':'accuracy','text':'Does Juniper Neighborhood Bakery have Orange Blossom Cookies?',
                  'product_id':'orange_cookies','target_field':'availability','context':''}]}
        return {'brand_mentioned':True,'claims':[{'product_id':'orange_cookies',
                'field':'availability','value':'unavailable','context':'',
                'quote':'does not sell Orange Blossom Cookies'}]}
    monkeypatch.setattr(ai,'call_ollama',fake_call)
    g=client.post('/api/questions/generate',json={'business_id':'juniper_bakery','visibility':1,'accuracy':1,'stress':0})
    assert g.status_code==200 and g.json()['actual']==2
    qid=next(x['id'] for x in g.json()['questions'] if x['type']=='accuracy')
    run=client.post('/api/answers',json={'question_id':qid,
         'answer':'Juniper Neighborhood Bakery does not sell Orange Blossom Cookies.',
         'citations':[],'extraction':'ollama'})
    assert run.status_code==200
    body=run.json()
    assert body['extraction_status']=='complete' and body['claims'][0]['verdict']=='INCORRECT'
    assert len(body['tickets_created'])==1

def test_ollama_fake_quote_rejected(client,monkeypatch):
    import ai
    monkeypatch.setattr(ai,'call_ollama',lambda *args: {'brand_mentioned':True,
        'claims':[{'product_id':'orange_cookies','field':'availability','value':'unavailable',
                   'context':'','quote':'an invented quote'}]})
    out=client.post('/api/answers',json={'question_id':'A001','answer':'Juniper Neighborhood Bakery sells cookies.','extraction':'ollama'})
    assert out.json()['extraction_status']=='failed'
    assert not out.json()['tickets_created']

def test_question_review_and_source_safety(client):
    new=client.post('/api/questions',json={'business_id':'juniper_bakery','type':'visibility',
       'text':'Where can I find a nearby independent bakery?'}).json()['id']
    edited=client.put(f'/api/questions/{new}',json={'business_id':'juniper_bakery',
      'type':'visibility','text':'Where can I find independent bakeries nearby?'}).json()
    assert edited['updated']==new
    assert client.post('/api/inspect-source',json={'url':'http://127.0.0.1/admin'}).status_code==400
    assert client.get('/api/templates/bistro.csv').status_code==200
