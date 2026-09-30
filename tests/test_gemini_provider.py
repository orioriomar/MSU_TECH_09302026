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
    assert ai.call_ai('extract claims','answer',ClaimBatch.model_json_schema()) == {
        'brand_mentioned':True,'claims':[]}

def test_missing_gemini_key_is_explicit(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    try: ai.call_gemini('instructions','text',QuestionBatch.model_json_schema())
    except ai.AIError as e:
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


def test_shopper_falls_back_to_no_search_when_search_quota_is_used_up(monkeypatch):
    """A 429 on the Google Search tool must not sink the check: the same question is asked
    without web search and the answer is labeled grounded=False."""
    import app
    calls = []

    class Resp:
        text = 'Try Casa Coqui Cafe.'
        candidates = []

    class Models:
        def generate_content(self, **kw):
            calls.append(bool(getattr(kw['config'], 'tools', None)))
            if calls[-1]:
                raise RuntimeError('429 RESOURCE_EXHAUSTED quota')
            return Resp()

    class Client:
        def __init__(self, api_key): self.models = Models()

    class Cfg:
        def __init__(self, **kw): self.__dict__.update(kw)
    fake_genai = types.ModuleType('google.genai'); fake_genai.Client = Client
    fake_types = types.ModuleType('google.genai.types')
    fake_types.GenerateContentConfig = Cfg
    fake_types.Tool = lambda **kw: kw
    fake_types.GoogleSearch = lambda: {}
    fake_google = types.ModuleType('google'); fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, 'google', fake_google)
    monkeypatch.setitem(sys.modules, 'google.genai', fake_genai)
    monkeypatch.setitem(sys.modules, 'google.genai.types', fake_types)
    monkeypatch.setenv('GEMINI_API_KEY', 'unit-test-key')
    answer, cites, grounded = app.ask_gemini_shopper('best cafe?')
    assert answer == 'Try Casa Coqui Cafe.' and cites == [] and grounded is False and calls == [True, False]
    monkeypatch.setenv('GEMINI_SEARCH_FALLBACK', '0')
    try:
        app.ask_gemini_shopper('best cafe?')
    except RuntimeError:
        pass
    else:
        raise AssertionError('fallback should be off')
