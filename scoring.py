"""This file calculates every score on the dashboard. No AI is involved,
so anyone can recompute the numbers by hand from the saved answers.
"""
from __future__ import annotations

# How much a wrong fact costs the business. Price and policy errors cause
# refunds, complaints and lost trust; availability and hours errors cause
# wasted trips; address errors are rarer but serious.
SEVERITY = {'price_usd': 3, 'policy': 3, 'availability': 2, 'hours': 2, 'address': 2}

# How the AI framed the business when it did mention it.
FRAMING = {'recommended': 1.0, 'neutral': 0.6, 'negative': 0.2}

# Weights for the combined AI Health Score (sum to 1). This is an internal, product-defined
# composite for tracking one business over time, not a validated industry index. The three
# parts are always shown separately next to it.
HEALTH_WEIGHTS = {'accuracy': 0.40, 'visibility': 0.35, 'reliability': 0.25}


def answered(results: list[dict]) -> list[dict]:
    """This drops questions that could not be asked (for example the AI service was down or out of
    quota). A failed call says nothing about the business, so it never counts for or against it.
    """
    return [r for r in results if not r.get('error')]


def visibility_points(vis: dict | None) -> float:
    """This scores one local search from 0 to 1: nothing if the business isn't mentioned,
    full points if it's recommended first, and less for a lower position or a neutral mention.
    """
    if not vis or not vis.get('mentioned'):
        return 0.0
    rank = max(int(vis.get('rank') or 1), 1)
    return (1.0 / rank) * FRAMING.get(vis.get('framing') or 'neutral', 0.6)


def visibility_score(results: list[dict]) -> dict:
    """This averages the local-search points into a 0-100 visibility score
    and counts how many searches mentioned the business.
    """
    vis = [r for r in answered(results) if r['type'] == 'visibility']
    if not vis:
        return {'score': None, 'inclusion_rate': None, 'questions': 0, 'mentioned': 0}
    mentioned = sum(1 for r in vis if (r.get('visibility') or {}).get('mentioned'))
    pts = [visibility_points(r.get('visibility')) for r in vis]
    return {'score': round(100 * sum(pts) / len(vis), 1),
            'inclusion_rate': round(100 * mentioned / len(vis), 1),
            'questions': len(vis), 'mentioned': mentioned}


def accuracy_score(results: list[dict]) -> dict:
    """This calculates the accuracy score: the share of checkable facts the AI got right, where
    serious mistakes (price, policy) count more than minor ones. Facts we can't verify never
    count against the business.
    """
    total_w = wrong_w = 0
    correct = incorrect = 0
    for r in answered(results):
        for c in r.get('claims', []):
            if c['verdict'] not in ('CORRECT', 'INCORRECT'):
                continue  # unverifiable / needs review never count as errors
            w = SEVERITY.get(c['field'], 1)
            total_w += w
            if c['verdict'] == 'INCORRECT':
                wrong_w += w
                incorrect += 1
            else:
                correct += 1
    if not total_w:
        return {'score': None, 'correct': 0, 'incorrect': 0}
    return {'score': round(100 * (1 - wrong_w / total_w), 1),
            'correct': correct, 'incorrect': incorrect}


def is_hallucination(r: dict) -> bool:
    """This decides whether a trick-question answer made something up.
    Admitting 'I'm not sure' is always treated as safe. Only two things count as made up:
    a confident claim that contradicts an approved fact (INCORRECT), or a confident "yes" to an
    offer that is not in the approved facts (unsupported). A claim we simply cannot check
    (UNVERIFIABLE / NEEDS_REVIEW) is never counted as a hallucination: unknown is not wrong.
    """
    if r.get('error') or r.get('abstained'):
        return False
    if r.get('unsupported'):
        return True
    return any(c['verdict'] == 'INCORRECT' for c in r.get('claims', []))


def hallucination_rate(results: list[dict]) -> dict:
    """This calculates the percentage of trick questions where the AI made something up."""
    stress = [r for r in answered(results) if r['type'] == 'stress']
    if not stress:
        return {'rate': None, 'questions': 0, 'hallucinated': 0, 'abstained': 0}
    bad = sum(1 for r in stress if is_hallucination(r))
    return {'rate': round(100 * bad / len(stress), 1), 'questions': len(stress),
            'hallucinated': bad, 'abstained': sum(1 for r in stress if r.get('abstained'))}


def health_score(acc: float | None, vis: float | None, hall_rate: float | None) -> float | None:
    """This combines the parts into the AI Health Score:
    40% accuracy + 35% visibility + 25% not making things up.
    Accuracy and visibility are both required: without them a business could score well just
    because the AI said "I don't know". If only the trick-question part is missing, the other two
    weights are scaled up to fill in. Otherwise there is no score (shown as "not enough data").
    """
    if acc is None or vis is None:
        return None
    parts = {'accuracy': acc, 'visibility': vis,
             'reliability': None if hall_rate is None else 100 - hall_rate}
    usable = {k: v for k, v in parts.items() if v is not None}
    weight = sum(HEALTH_WEIGHTS[k] for k in usable)  # renormalize if reliability is missing
    return round(sum(HEALTH_WEIGHTS[k] * v for k, v in usable.items()) / weight, 1)


def question_outcome(r: dict) -> str:
    """This gives each question a one-word result for the dashboard,
    e.g. TOP, LISTED, ABSENT, CORRECT, WRONG, SAFE, HALLUCINATED.
    """
    if r.get('error'):
        return 'ERROR'
    if r['type'] == 'visibility':
        v = r.get('visibility') or {}
        return 'ABSENT' if not v.get('mentioned') else ('TOP' if v.get('rank') == 1 else 'LISTED')
    if r['type'] == 'stress':
        return 'HALLUCINATED' if is_hallucination(r) else 'SAFE'
    verdicts = [c['verdict'] for c in r.get('claims', [])]
    if 'INCORRECT' in verdicts:
        return 'WRONG'
    if 'CORRECT' in verdicts:
        return 'CORRECT'
    return 'NO CLAIM'


def scorecard(results: list[dict]) -> dict:
    """This builds the full set of scores for one weekly check."""
    vis = visibility_score(results)
    acc = accuracy_score(results)
    hal = hallucination_rate(results)
    ok = answered(results)
    return {'health': health_score(acc['score'], vis['score'], hal['rate']),
            'visibility': vis, 'accuracy': acc, 'hallucination': hal,
            'questions': len(results), 'answered': len(ok), 'errors': len(results) - len(ok)}


def compare(before: dict, after: dict) -> dict:
    """This works out how much each score changed between two weekly checks."""
    def d(a, b):
        """This subtracts two numbers, or returns nothing if either one is missing."""
        return None if a is None or b is None else round(b - a, 1)
    return {'health': d(before.get('health', before.get('trust')), after.get('health', after.get('trust'))),
            'visibility': d(before['visibility']['score'], after['visibility']['score']),
            'inclusion_rate': d(before['visibility']['inclusion_rate'], after['visibility']['inclusion_rate']),
            'accuracy': d(before['accuracy']['score'], after['accuracy']['score']),
            'hallucination_rate': d(before['hallucination']['rate'], after['hallucination']['rate'])}
