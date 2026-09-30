"""This file supports the weekly check. It loads each business's locked question list and demo
answers, reads live answers to see whether the business was mentioned, and measures how
accurate our own claim extractor is.
"""
from __future__ import annotations
import json, re
from pathlib import Path

BASE = Path(__file__).resolve().parent
MOCK_MODES = {'mock_baseline': 'runs_baseline.json', 'mock_after': 'runs_after.json'}

ABSTAIN = re.compile(r"(couldn'?t|could not|can'?t|cannot|unable to) (confirm|verify|find)|"
                     r"not sure|no information|best to (ask|contact|call)|recommend (contacting|calling)", re.I)
POSITIVE = re.compile(r'\b(recommend|best|top pick|favorite|standout|strong pick|must[- ]try|go-to)\b', re.I)
NEGATIVE = re.compile(r'\b(avoid|mixed reviews|disappointing|overpriced|poor|complaints?)\b', re.I)


def business_dir(business_id: str) -> Path:
    """This returns the data folder for a business."""
    return BASE / 'data' / business_id


def load_eval_set(business_id: str) -> dict | None:
    """This loads a business's locked question list (the same questions every week)."""
    p = business_dir(business_id) / 'questions.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def load_mock(business_id: str, mode: str) -> dict:
    """This loads the hand-written demo answers for Week 1 or Week 3."""
    p = business_dir(business_id) / MOCK_MODES[mode]
    if not p.exists():
        raise FileNotFoundError(f'No mock answers for {business_id} ({mode}).')
    return json.loads(p.read_text(encoding='utf-8'))


def load_profile(business_id: str) -> dict | None:
    """This loads the demo business profile and its website signals."""
    p = business_dir(business_id) / 'profile.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


AFFIRM = re.compile(r"^\W*(yes|yep|yeah|absolutely|definitely|of course|sure|indeed)\b", re.I)


def detect_affirmation(answer: str) -> bool:
    """This spots when an answer to a trick question starts by saying yes ('Yes! They have a
    Monday happy hour...'). Our trick questions ask about things that aren't in the approved facts,
    so a confident yes means the AI made something up."""
    return bool(AFFIRM.search(answer or ''))


def detect_abstention(answer: str) -> bool:
    """This spots when an AI answer admits it doesn't know ('couldn't confirm', 'best to call them')."""
    return bool(ABSTAIN.search(answer or ''))


def parse_visibility(answer: str, brand: str) -> dict:
    """This reads a LIVE answer and works out whether the business was mentioned, where it ranked
    in the list, and whether it was recommended, neutral or negative. It uses simple text rules
    (not AI), so the same answer always gets the same result.
    """
    text = answer or ''
    low = text.lower()
    key = brand.lower()
    plain = key.replace('í', 'i').replace('é', 'e').replace('á', 'a').replace('ó', 'o').replace('ú', 'u')
    idx = low.find(key)
    if idx < 0:
        idx = low.replace('í', 'i').replace('é', 'e').replace('á', 'a').replace('ó', 'o').replace('ú', 'u').find(plain)
    if idx < 0:
        return {'mentioned': False, 'rank': None, 'framing': None}
    items = [ln for ln in text.splitlines() if re.match(r'\s*(\d+[.)]|[-*•])\s+', ln)]
    rank = None
    for i, ln in enumerate(items, 1):
        if key in ln.lower() or plain in ln.lower():
            rank = i
            break
    if rank is None:
        numbered = re.findall(r'(\d+)[.)]\s+([^,;\n]+)', text)
        for n, chunk in numbered:
            if key in chunk.lower() or plain in chunk.lower():
                rank = int(n)
                break
    if rank is None:  # prose answer: rank by order of capitalized names before the brand
        before = text[:idx]
        rank = 1 + len(re.findall(r'\b[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+\b', before))
    start = max(text.rfind('.', 0, idx), text.rfind('\n', 0, idx)) + 1
    end_candidates = [p for p in (text.find('.', idx), text.find('\n', idx)) if p != -1]
    sentence = text[start:min(end_candidates) if end_candidates else len(text)]
    framing = 'negative' if NEGATIVE.search(sentence) else ('recommended' if POSITIVE.search(sentence) else 'neutral')
    return {'mentioned': True, 'rank': max(rank, 1), 'framing': framing}


def claim_key(c: dict) -> tuple:
    """This turns a claim into a standard form so two claims can be compared exactly."""
    from verifier import normalize
    return (c['product_id'], c['field'], (c.get('context') or '').strip().lower(),
            normalize(c['field'], c['value'], c.get('context') or '') or str(c['value']).strip().lower())


def extractor_metrics(gold: list[tuple], predicted: list[tuple]) -> dict:
    """This compares the extractor's claims with the hand-labeled answer key
    and calculates precision and recall.
    """
    g, p = set(gold), set(predicted)
    tp = len(g & p)
    precision = tp / len(p) if p else (1.0 if not g else 0.0)
    recall = tp / len(g) if g else (1.0 if not p else 0.0)
    return {'tp': tp, 'fp': len(p - g), 'fn': len(g - p),
            'precision': round(100 * precision, 1), 'recall': round(100 * recall, 1)}
