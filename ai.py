"""This file holds the two jobs Gemini does for us:
  1. writing realistic shopper questions, and
  2. pulling factual claims out of AI answers.
Gemini never decides what is true. Python does that in verifier.py.
"""
from __future__ import annotations
import json, os, re
import requests
from pydantic import ValidationError
from models import QuestionBatch, ClaimBatch

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
AI_PROVIDER = os.getenv('AI_PROVIDER', 'gemini').lower()

class AIError(Exception):
    """This is the error raised whenever an AI call fails (Gemini, or the optional local Ollama)."""
    pass


def is_quota_error(exc: Exception) -> bool:
    """This spots Google's "too many requests / quota used up" error (HTTP 429)."""
    msg = str(exc)
    return '429' in msg or 'RESOURCE_EXHAUSTED' in msg or 'quota' in msg.lower()


def friendly_error(exc: Exception) -> str:
    """This turns a provider error into a short message that is safe to show on the dashboard.
    The raw provider text (which can include URLs and account details) stays in the server log only.
    """
    if is_quota_error(exc):
        return 'Gemini quota reached. This question was not scored.'
    if isinstance(exc, AIError):
        return str(exc)[:160]
    return 'The live AI call failed. This question was not scored.'


def with_quota_retry(call, attempts: int = 3):
    """This retries a Gemini call when Google says we're going too fast (error 429,
    RESOURCE_EXHAUSTED). It waits the time Google suggests (or 15s, then 30s) before trying again.
    If the DAILY free quota is used up, retrying can't help, so after the last attempt the
    error is passed on and the dashboard shows it.
    """
    import time
    for i in range(attempts):
        try:
            return call()
        except Exception as exc:
            msg = str(exc)
            if ('429' not in msg and 'RESOURCE_EXHAUSTED' not in msg) or i == attempts - 1:
                raise
            m = re.search(r"retry(?:Delay)?['\"]?\s*[:in ]+\s*['\"]?(\d+(?:\.\d+)?)s", msg, re.I)
            wait = min(float(m.group(1)) + 1, 60) if m else 15 * (i + 1)
            print(f'GEMINI RATE LIMIT: waiting {wait:.0f}s before retrying ({i + 1}/{attempts - 1})')
            time.sleep(wait)

def call_gemini(system: str, prompt: str, schema: dict) -> dict:
    """This sends instructions to Gemini, asks for a JSON reply in the exact shape we need,
    and returns it. If the call fails, it prints the real error to the server log.
    """
    if not os.getenv('GEMINI_API_KEY'):
        raise AIError('GEMINI_API_KEY is missing. Add it to .env and restart Proof Flower.')
    try:
        from google import genai
        from google.genai import types
        # The SDK accepts a Pydantic schema; we reuse the same models as the
        # Python validator. Never transmit expected fact VALUES to extraction.
        target = QuestionBatch if 'questions' in schema.get('properties', {}) else ClaimBatch
        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        response = with_quota_retry(lambda: client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system + '\n\nReturn ONLY a JSON object matching this JSON Schema:\n' + json.dumps(target.model_json_schema()),
                response_mime_type='application/json',
                temperature=0,
            ),
        ))
        if not response.text:
            raise AIError('Gemini returned no JSON. Try again or check your API quota.')
        return json.loads(response.text)
    except AIError:
        raise
    except Exception as exc:
        print('GEMINI ERROR:', exc)  # server log only; never shown to end users
        # We deliberately omit provider exception text; it could include URLs
        # and other details not appropriate for an end-user or shared log.
        raise AIError('Gemini request failed. Check the API key, model access, network, and rate limits.') from exc

def call_ai(system: str, prompt: str, schema: dict) -> dict:
    """This sends a request to whichever AI provider is set in .env
    (Gemini by default, or a local Ollama model).
    """
    if AI_PROVIDER == 'gemini':
        return call_gemini(system, prompt, schema)
    if AI_PROVIDER != 'ollama':
        raise AIError('AI_PROVIDER must be gemini or ollama.')
    try:
        response = requests.post(
            f'{OLLAMA_URL.rstrip("/")}/api/chat',
            json={
                'model': OLLAMA_MODEL,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': prompt}],
                'format': schema, 'stream': False,
                'options': {'temperature': 0}
            }, timeout=150)
        response.raise_for_status()
        return json.loads(response.json()['message']['content'])
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise AIError('Ollama is unavailable or returned invalid JSON. Run: ollama pull llama3.2; ollama serve') from exc

def generate_questions(business_name: str, facts: list[dict], counts: dict,
                       location: str = '', category: str = '') -> QuestionBatch:
    """This asks Gemini to write realistic shopper questions from the business's approved facts,
    then throws out duplicates, questions about unknown products, and 'local search'
    questions that accidentally name the business.
    """
    available = [{'product_id': f['product_id'], 'product_name': f['product_name'],
                  'field': f['field'], 'context': f['context']}
                 for f in facts if f['approved']]
    if not available:
        raise AIError('Review/approve some catalog facts before generating questions.')
    needed = sum(counts.values())
    system = (
        'You generate realistic, neutral shopper questions for a small-business visibility/accuracy study. '
        'Return JSON matching the given schema ONLY. Do not make up facts about the business. '
        'Write EVERY question as a real shopper typing into an AI assistant like ChatGPT. '
        'Never address the business directly and never use "you" to mean the business. '
        'visibility: generic discovery question WITHOUT naming the business, including shopper_location if provided '
        '(otherwise say "near me"), e.g. "What are the best bakeries in Dallas for citrus desserts?" '
        '(product_id and target_field must be empty). '
        'accuracy: ask about one specific approved product and field. '
        'stress: ask a cautious question that tests unsupported assumptions or uncertain details; '
        'do not imply a false deal, wrongdoing, or assert an unsupported fact. '
        'Use only the provided product IDs. Do not include the correct answer inside the question. '
        'Return exactly the requested counts of each type, with no duplicates.'
    )
    prompt = json.dumps({'business': business_name, 'business_category': category,
                         'shopper_location': location or os.getenv('SHOPPER_LOCATION', ''), 'approved_fact_descriptors': available,
                         'requested_counts': counts, 'total': needed}, ensure_ascii=False)
    raw = call_ai(system, prompt, QuestionBatch.model_json_schema())
    try:
        batch = QuestionBatch.model_validate(raw)
    except ValidationError as exc:
        raise AIError('AI question output failed the question schema. Try again.') from exc
    product_ids = {f['product_id'] for f in facts if f['approved']}
    allowed = {f['field'] for f in facts if f['approved']}
    seen, approved = set(), []
    accepted_counts = {kind: 0 for kind in counts}
    known_pairs = {(f['product_id'], f['field']) for f in facts if f['approved']}
    for q in batch.questions:
        if accepted_counts.get(q.type, 0) >= counts.get(q.type, 0): continue
        key = q.text.strip().lower()
        if key in seen: continue
        if q.type != 'visibility' and q.product_id not in product_ids: continue
        if q.type == 'accuracy' and (q.product_id, q.target_field) not in known_pairs: continue
        if q.type == 'visibility' and business_name.lower() in key: continue
        seen.add(key)
        approved.append(q)
        accepted_counts[q.type] += 1
    # Never invent missing questions to satisfy requested counts.
    if not approved:
        raise AIError('No usable questions after validating model output. Try again.')
    return QuestionBatch(questions=approved[:needed])

def extract_claims(answer: str, question: dict, business_name: str, facts: list[dict]) -> ClaimBatch:
    """This asks Gemini to pull every factual claim out of an AI answer (price, hours, availability,
    policy, address). Each claim must include an exact quote from the answer. If Gemini invents a
    quote or a product, the whole extraction is rejected and no ticket is created.
    """
    descriptors = [{'product_id': f['product_id'], 'product_name': f['product_name'],
                    'field': f['field'], 'context': f['context']} for f in facts]
    system = (
        'You are a conservative DATA EXTRACTOR, not a fact checker. '
        'Return only JSON matching the provided schema. '
        'Extract only claims EXPLICITLY stated in the ANSWER about the listed business and products. '
        'Do not infer that a missing product is unavailable. Do not infer a price from an adjacent product. '
        'Preserve lunch vs dinner, per-item vs per-dozen, location, and historical vs current context. '
        'For availability, normalize the value to available or unavailable. '
        'For price_usd, return a number string without a dollar symbol. '
        'For every claim, quote MUST be an exact, continuous substring of the answer that supports it. '
        'If you cannot locate an exact supporting quote, omit that claim. '
        'If a product/configuration is ambiguous, omit the claim; NEVER guess its product_id. '
        'An unsupported offer not listed in the catalog must NOT become an invented catalog claim. '
        'brand_mentioned indicates whether the brand is explicitly named in the answer.'
    )
    prompt = json.dumps({'question': question['text'], 'answer': answer,
                         'brand': business_name, 'product_field_descriptors': descriptors}, ensure_ascii=False)
    raw = call_ai(system, prompt, ClaimBatch.model_json_schema())
    try:
        batch = ClaimBatch.model_validate(raw)
    except ValidationError as exc:
        raise AIError('AI extraction did not match the required schema; no tickets created.') from exc
    def squash(s):
        """This collapses extra spaces so quote matching isn't thrown off by formatting."""
        return re.sub(r'\s+', ' ', s).strip()
    allowed = {(f['product_id'],f['field']) for f in facts}
    for c in batch.claims:
        if (c.product_id,c.field) not in allowed:
            raise AIError(f'Extractor invented an unknown product/field: {c.product_id}/{c.field}')
        if squash(c.quote) not in squash(answer):
            raise AIError('Extractor returned a quote absent from the AI answer; no tickets created.')
    return batch
