import sys, types, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai
from models import ClaimBatch, QuestionBatch

class FakeResponse:
    text='{"brand_mentioned": true, "claims": []}'

class FakeModels:
    def generate_content(self, **kwargs):
        assert kwargs['model'] == ai.GEMINI_MODEL
        assert kwargs['config'].response_mime_type == 'application/json'
        return FakeResponse()

class FakeClient:
    def __init__(self, api_key):
        assert api_key == 'unit-test-key'
        self.models=FakeModels()

def test_gemini_structured_output_dispatch(monkeypatch):
    fake_genai=types.ModuleType('google.genai')
    fake_genai.Client=FakeClient
    class FakeConfig:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    fake_types=types.ModuleType('google.genai.types')
    fake_types.GenerateContentConfig=FakeConfig
    fake_google=types.ModuleType('google')
    fake_google.genai=fake_genai
    monkeypatch.setitem(sys.modules,'google',fake_google)
    monkeypatch.setitem(sys.modules,'google.genai',fake_genai)
    monkeypatch.setitem(sys.modules,'google.genai.types',fake_types)
    monkeypatch.setenv('GEMINI_API_KEY','unit-test-key')
    monkeypatch.setattr(ai,'AI_PROVIDER','gemini')
    assert ai.call_ollama('extract claims','answer',ClaimBatch.model_json_schema()) == {
        'brand_mentioned':True,'claims':[]}

def test_missing_gemini_key_is_explicit(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    try: ai.call_gemini('instructions','text',QuestionBatch.model_json_schema())
    except ai.OllamaError as e:
        assert 'GEMINI_API_KEY' in str(e)
    else: raise AssertionError('Missing key should fail')


def test_gemini_status_and_live_endpoint_without_key(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    import app
    monkeypatch.setattr(app,'DB',tmp_path/'isolated.sqlite3')
    app.init_db()
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    client=TestClient(app.app)
    r=client.get('/api/status')
    assert r.json()['gemini_configured'] is False
    r=client.post('/api/run-live-gemini',json={'question_id':'A001'})
    assert r.status_code==400
