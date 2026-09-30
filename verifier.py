"""This file decides what is true. It compares each claim with the business's
approved facts using plain code, not AI. Unclear matches never open a ticket.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re

DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
_DAY = r'(mon|tue|wed|thu|fri|sat|sun)[a-z]*'
_TIME = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?'


def _minutes(h, m, ap):
    """This turns an hour, minutes and optional am/pm into minutes after midnight."""
    h, m = int(h), int(m or 0)
    ap = (ap or '').replace('.', '')
    if ap == 'pm' and h < 12:
        h += 12
    if ap == 'am' and h == 12:
        h = 0
    return h * 60 + m


def canonical_hours(text: str):
    """This reads opening hours written almost any common way ("tue-sun 11:00-21:00, closed monday",
    "Tuesday through Sunday, 11 AM to 9 PM", "open daily 11am-9pm") and returns the same standard
    form for each, so different wording of the same hours counts as a match. Returns None if the
    hours are too complicated to read safely, which sends the claim to human review instead.
    """
    t = ' ' + str(text).lower().replace('–', '-').replace('—', '-') + ' '
    t = re.sub(r'\b(to|through|thru|until|till)\b', '-', t)
    t = re.sub(r'\bnoon\b', '12pm', t)
    ranges = []
    for m in re.finditer(_TIME + r'\s*-\s*' + _TIME, t):
        h1, m1, a1, h2, m2, a2 = m.groups()
        if not a1 and a2 and int(h1) <= 12:  # "11-9pm": guess the opening half of the day
            a1 = 'am' if int(h1) < 12 and _minutes(h1, m1, a2) >= _minutes(h2, m2, a2) else a2
        o, c = _minutes(h1, m1, a1), _minutes(h2, m2, a2)
        if c <= o and not a2 and int(h2) < 12:  # "11-9" with no am/pm means 11am-9pm
            c += 12 * 60
        ranges.append((o, c))
    ranges = sorted(set(ranges))
    if len(ranges) != 1:
        return None  # no times, or different hours on different days: let a person check
    closed = set()
    for m in re.finditer(r'closed\s+(?:on\s+)?((?:' + _DAY + r')(?:\s*(?:,|and|&|/|-)\s*(?:' + _DAY + r'))*)', t):
        for d in re.findall(_DAY, m.group(1)):
            closed.add(DAYS.index(d))
        t = t.replace(m.group(0), ' ')
    open_days = set()
    if re.search(r'\b(daily|every ?day|7 days|seven days)\b', t):
        open_days = set(range(7))
    for m in re.finditer(_DAY + r'\s*-\s*' + _DAY, t):
        a, b = DAYS.index(m.group(1)), DAYS.index(m.group(2))
        open_days |= {(a + i) % 7 for i in range((b - a) % 7 + 1)}
        t = t.replace(m.group(0), ' ')
    for d in re.findall(r'\b' + _DAY + r'\b', t):
        open_days.add(DAYS.index(d))
    if not open_days:
        if not closed:
            return None  # no days mentioned at all: can't tell
        open_days = set(range(7))
    open_days -= closed
    o, c = ranges[0]
    return ' '.join(f'{DAYS[i]}={o}-{c}' if i in open_days else f'{DAYS[i]}=closed' for i in range(7))


_ABBR = {'street': 'st', 'avenue': 'ave', 'road': 'rd', 'boulevard': 'blvd', 'drive': 'dr', 'suite': 'ste',
         'place': 'pl', 'lane': 'ln', 'court': 'ct', 'highway': 'hwy', 'north': 'n', 'south': 's',
         'east': 'e', 'west': 'w', 'new jersey': 'nj', 'texas': 'tx', 'new york': 'ny'}


def canonical_address(text: str):
    """This reduces an address to its house number, first street word and ZIP code, so
    "118 Market Street, Paterson NJ" and "118 Market St., Paterson, NJ 07505" match.
    Returns None if there's no house number to anchor on.
    """
    s = ' ' + str(text).lower() + ' '
    for k, v in _ABBR.items():
        s = re.sub(r'\b' + k + r'\b', v, s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    m = re.search(r'\b(\d+[a-z]?)\s+([a-z0-9]+)', s)
    if not m:
        return None
    z = re.search(r'\b(\d{5})\b', s[m.end():])
    return f'{m.group(1)} {m.group(2)}' + (f' {z.group(1)}' if z else '')


def canonical_policy(value: str, context: str):
    """This turns a policy written in any words into a standard answer for the common policies:
    delivery, reservations, takeout, catering minimum and returns. For example "pickup only" and
    "we don't deliver" both become "no delivery"; "delivery via DoorDash" becomes "delivery".
    Returns None for anything it can't read confidently, which sends it to human review.
    """
    v, ctx = str(value).lower(), (context or '').lower()
    if 'deliver' in ctx:
        if re.search(r"no deliver|pick-?up only|take-?out only|carry-?out only|(does not|doesn'?t|don'?t|do not) (offer )?deliver|not (offer|provide) delivery", v):
            return 'no delivery'
        if re.search(r'deliver|doordash|uber ?eats|grubhub|postmates|caviar', v):
            return 'delivery'
        return None
    if 'reserv' in ctx:
        if re.search(r"walk-?ins? only|no reservation|(does not|doesn'?t|don'?t|do not|not) (take|accept) reservation|first.come", v):
            return 'no reservations'
        if re.search(r'reserv|opentable|resy|book a table|booking', v):
            return 'reservations'
        return None
    if any(k in ctx for k in ('takeout', 'take-out', 'pickup', 'carry')):
        if re.search(r'no take-?out|dine-?in only|no pick-?up', v):
            return 'no takeout'
        if re.search(r'take-?out|to go|pick-?up|carry-?out', v):
            return 'takeout'
        return None
    if 'cater' in ctx:
        if re.search(r"no catering|(does not|doesn'?t|don'?t) cater", v):
            return 'no catering'
        n = re.search(r'\d+', v)
        return f'minimum {n.group(0)}' if n else None
    if 'return' in ctx or 'refund' in ctx:
        if re.search(r'no (returns|refunds)|final sale', v):
            return 'no returns'
        n = re.search(r'\d+', v)
        return f'{n.group(0)} days' if n else None
    # A policy type we have no rules for: only identical wording can be confirmed.
    # Different wording is NOT treated as wrong; verify() sends it to human review.
    plain = re.sub(r'\s+', ' ', v).strip(' .')
    return f'text:{plain}' if plain else None


def normalize(field: str, value: str, context: str = '') -> str | None:
    """This puts values in a standard form before comparing them.
    Prices: '$14' and '14.00' both become '14.00'. Availability: 'in stock' becomes 'available'.
    Hours, addresses and policies are read by the canonical_* helpers above, so the same fact
    written in different words still matches. None means "can't read it safely".
    """
    s = str(value).strip().lower()
    if field == 'price_usd':
        # Exactly one number must be present: "$14", "14.00", "14 dollars" all become "14.00".
        # Ranges ("$14-16") or several numbers are ambiguous, so they go to human review.
        nums = re.findall(r'\d[\d,]*(?:\.\d+)?', s)
        if len(nums) != 1 or re.search(r'\d\s*(-|–|to)\s*\$?\d', s):
            return None
        try:
            v = Decimal(nums[0].replace(',', ''))
            return str(v.quantize(Decimal('0.01'))) if v >= 0 else None
        except InvalidOperation:
            return None
    if field == 'availability':
        if s in ('available', 'yes', 'in stock', 'on menu', 'on the menu', 'served', 'open', 'open for business'):
            return 'available'
        if s in ('unavailable', 'no', 'out of stock', 'not on menu', 'not on the menu', 'not served',
                 'not available', 'discontinued', 'closed', 'permanently closed'):
            return 'unavailable'
        return None
    if field == 'hours':
        return canonical_hours(value)
    if field == 'address':
        return canonical_address(value)
    if field == 'policy':
        return canonical_policy(value, context)
    return re.sub(r'\s+', ' ', s).strip(' .') or None


def same_value(field: str, observed: str, expected: str) -> bool:
    """This compares two standardized values. For addresses the ZIP code only counts when BOTH
    sides give one, so "118 Market St, Paterson" is not called wrong just for leaving out the ZIP.
    """
    if field == 'address':
        o, e = observed.split(), expected.split()
        return o[:2] == e[:2] and (len(o) < 3 or len(e) < 3 or o[2] == e[2])
    return observed == expected


def verify(claim: dict, facts: list[dict]) -> dict:
    """This checks one claim against the approved facts and returns one of:
      CORRECT       the claim matches the approved fact
      INCORRECT     the claim contradicts it (this is the only verdict that opens a ticket)
      NEEDS_REVIEW  the context is unclear, e.g. the answer didn't say lunch or dinner
      UNVERIFIABLE  we have no approved fact for it; this is never counted as an error
    """
    group = [f for f in facts if f['approved'] and f['product_id'] == claim['product_id']
             and f['field'] == claim['field']]
    if not group:
        return {'verdict':'UNVERIFIABLE','reason':'No reviewed reference fact for product/field.'}
    context = (claim.get('context') or '').strip().lower()
    if context:
        group = [f for f in group if f['context'].strip().lower() == context]
    elif len(group) == 1 and not group[0]['context']:
        pass
    else:
        return {'verdict':'NEEDS_REVIEW','reason':'Missing or ambiguous context (e.g., lunch vs. dinner).'}
    if len(group) != 1:
        return {'verdict':'NEEDS_REVIEW','reason':'No unique approved reference for this exact context.'}
    fact = group[0]
    observed = normalize(claim['field'], claim['value'], fact['context'])
    expected = normalize(claim['field'], fact['value'], fact['context'])
    if observed is None or expected is None:
        return {'verdict':'NEEDS_REVIEW','reason':'Value could not be safely normalized.','fact':fact}
    if claim['field'] == 'policy' and observed.startswith('text:') and observed != expected:
        return {'verdict': 'NEEDS_REVIEW', 'reason': 'Unrecognized policy wording; a person must compare it.', 'fact': fact}
    verdict = 'CORRECT' if same_value(claim['field'], observed, expected) else 'INCORRECT'
    # Show people the original wording for hours/address/policy; the standard form is only for comparing.
    readable = claim['field'] in ('hours', 'address', 'policy')
    return {'verdict': verdict, 'reason': 'Exact reviewed catalog comparison.', 'fact': fact,
            'observed': str(claim['value']).strip() if readable else observed,
            'expected': str(fact['value']).strip() if readable else expected}

def suggested_action(field: str) -> str:
    """This returns the plain-language next step shown on a ticket, based on what kind of fact was wrong.
    It only suggests; nothing is changed until the owner approves.
    """
    return {
        'price_usd': 'Check the page the AI cited. If it shows an old price, update your menu page and '
                     'listings (Google, Yelp, delivery apps) so they match your current price.',
        'availability': 'Make sure this item is listed as text on your own menu page, then ask outdated '
                        'listings to update it. AI often says an item is missing when the menu is only a PDF or photo.',
        'address': 'Correct the address on every public listing so it matches your website exactly.',
        'hours': 'Make your hours identical on your website, Google Business Profile and Yelp.',
        'policy': 'Publish this policy in one clear sentence on your website (FAQ) and fix any listing that says otherwise.',
    }.get(field, 'Review the cited information before deciding on any change.')
