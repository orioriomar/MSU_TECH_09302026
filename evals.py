"""This file supports the weekly check. It loads each business's locked question list and demo
answers, reads live answers to see whether the business was mentioned, and measures how
accurate our own claim extractor is.
"""
from __future__ import annotations
import json, re, unicodedata
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


COMMON_WORDS = {'for', 'in', 'the', 'try', 'near', 'at', 'and', 'or', 'if', 'you', 'best', 'top', 'good',
                'great', 'north', 'south', 'east', 'west', 'new', 'jersey', 'york', 'nj', 'ny', 'here', 'some'}


def fold(text: str) -> str:
    """This lowercases text and strips accents, so "Casa Coquí Café" and "casa coqui cafe" match."""
    return ''.join(ch for ch in unicodedata.normalize('NFKD', text or '') if not unicodedata.combining(ch)).lower()


def parse_visibility(answer: str, brand: str, question: str = '') -> dict:
    """This reads a LIVE answer and works out whether the business was mentioned, where it ranked
    in the list, and whether it was recommended, neutral or negative. It uses simple text rules
    (not AI), so the same answer always gets the same result. The rank is a heuristic: a numbered
    or bulleted list gives an exact position; in plain prose we count the other business names
    that appear before ours (ignoring place and cuisine words that were already in the question).
    """
    text = answer or ''
    low, key = fold(text), fold(brand)
    idx = low.find(key)
    if not key or idx < 0:
        return {'mentioned': False, 'rank': None, 'framing': None}
    items = [ln for ln in text.splitlines() if re.match(r'\s*(\d+[.)]|[-*•])\s+', ln)]
    rank = None
    for i, ln in enumerate(items, 1):
        if key in fold(ln):
            rank = i
            break
    if rank is None:
        for n, chunk in re.findall(r'(\d+)[.)]\s+([^,;\n]+)', text):
            if key in fold(chunk):
                rank = int(n)
                break
    if rank is None:  # prose answer: rank by order of other capitalized names before the brand
        asked = set(re.findall(r'[a-z]+', fold(question))) | COMMON_WORDS
        names = re.findall(r'\b[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+\b', text[:idx])
        rank = 1 + len({n for n in names if set(re.findall(r'[a-z]+', fold(n))) - asked})
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
