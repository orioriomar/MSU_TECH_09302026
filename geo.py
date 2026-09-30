"""This file builds the growth plan (GEO: getting found in AI answers). It can inspect a real
website, uses simple rules to decide what to recommend, and writes draft fixes from approved
facts. Nothing is ever published without the owner's approval.
"""
from __future__ import annotations
import ipaddress, json, os, re, socket
from urllib.parse import urlparse, urljoin
import requests

AI_BOTS = ['GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'Google-Extended',
           'PerplexityBot', 'ClaudeBot', 'anthropic-ai', 'CCBot']
LOCAL_SCHEMA = {'LocalBusiness', 'Restaurant', 'Store', 'FoodEstablishment', 'Organization',
                'Product', 'Menu', 'FAQPage', 'CafeOrCoffeeShop', 'Bakery'}
UA = {'User-Agent': 'ProofFlowerGEOAudit/1.0 (+hackathon research)'}


# ---------------------------------------------------------------- safe fetch
def _public(host: str) -> bool:
    """This makes sure a web address points to the public internet, not a private or internal machine."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
    except Exception:
        return False


def safe_get(url: str, max_bytes: int = 1_500_000, redirects: int = 3) -> requests.Response | None:
    """This downloads a public https web page safely: it re-checks every redirect,
    limits the size, and gives up quietly on errors.
    """
    for _ in range(redirects + 1):
        u = urlparse(url)
        if (u.scheme != 'https' or not u.hostname or u.port not in (None, 443) or u.username or u.password
                or not _public(u.hostname)):
            return None
        try:
            r = requests.get(url, timeout=8, allow_redirects=False, stream=True, headers=UA)
        except requests.RequestException:
            return None
        if 300 <= r.status_code < 400 and r.headers.get('Location'):
            url = urljoin(url, r.headers['Location'])
            continue
        body, size = [], 0
        for chunk in r.iter_content(16384):
            size += len(chunk)
            if size > max_bytes:
                break
            body.append(chunk)
        r._content = b''.join(body)
        return r
    return None


# ---------------------------------------------------------------- site audit
def robots_blocked_bots(robots_txt: str) -> list[str]:
    """This reads a website's robots.txt file and lists which AI assistants
    are completely blocked from reading the site.
    """
    blocked, agents, group_rules = set(), [], []

    def close():
        """This finishes one block of robots.txt rules and records any AI assistants it blocks."""
        if any(rule == '/' for rule in group_rules):
            for a in agents:
                if a == '*':
                    blocked.update(AI_BOTS)
                else:
                    for bot in AI_BOTS:
                        if a.lower() == bot.lower():
                            blocked.add(bot)

    last_was_agent = False
    for raw in robots_txt.splitlines():
        line = raw.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        key, val = [p.strip() for p in line.split(':', 1)]
        key = key.lower()
        if key == 'user-agent':
            if not last_was_agent:
                close()
                agents, group_rules = [], []
            agents.append(val)
            last_was_agent = True
        elif key == 'disallow':
            group_rules.append(val)
            last_was_agent = False
        else:
            last_was_agent = False
    close()
    return sorted(blocked)


def site_audit(url: str) -> dict:
    """This checks a real website's AI-readiness: blocked AI assistants, business info markup
    (schema.org), an FAQ, the menu format, a homepage description, and an llms.txt file.
    """
    from bs4 import BeautifulSoup
    u = urlparse(url)
    if u.scheme != 'https' or not u.hostname:
        raise ValueError('Enter a public https:// website URL.')
    home = safe_get(url)
    if home is None or home.status_code >= 400:
        raise ValueError('Could not fetch that website (must be public HTTPS).')
    root = f'https://{urlparse(home.url or url).hostname}'
    robots = safe_get(root + '/robots.txt', max_bytes=200_000)
    llms = safe_get(root + '/llms.txt', max_bytes=200_000)
    soup = BeautifulSoup(home.content, 'html.parser')

    schema_types = set()
    def dig(node):
        """This searches the page's structured data for business types such as Restaurant or Menu."""
        if isinstance(node, list):
            for x in node:
                dig(x)
        elif isinstance(node, dict):
            t = node.get('@type')
            for x in ([t] if isinstance(t, str) else (t or [])):
                schema_types.add(x)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    dig(v)
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            dig(json.loads(tag.string or tag.get_text() or '{}'))
        except json.JSONDecodeError:
            pass

    for n in soup(['script', 'style', 'noscript']):
        n.decompose()
    text = ' '.join(soup.stripped_strings)
    links = [a.get('href', '') for a in soup.find_all('a')]
    pdf_links = [h for h in links if h.lower().split('?')[0].endswith('.pdf')]
    meta = soup.find('meta', attrs={'name': 'description'})
    return {
        'website': url, 'synthetic': False,
        'ai_bots_blocked': robots_blocked_bots(robots.text) if robots is not None and robots.status_code < 400 else [],
        'robots_found': robots is not None and robots.status_code < 400,
        'schema_types': sorted(schema_types),
        'menu_format': 'pdf' if pdf_links and not re.search(r'\$\s?\d', text) else ('html' if re.search(r'\$\s?\d', text) else 'unknown'),
        'has_faq': 'FAQPage' in schema_types or bool(re.search(r'\bFAQ|frequently asked', text, re.I)),
        'meta_description': bool(meta and meta.get('content', '').strip()),
        'llms_txt': llms is not None and llms.status_code == 200 and len(llms.text.strip()) > 0,
        'has_hours_text': bool(re.search(r'\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b.{0,40}\d', text, re.I)),
        'has_phone': bool(re.search(r'\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}', text)),
        'word_count': len(text.split()),
        'title': soup.title.get_text(strip=True) if soup.title else '',
    }


# ---------------------------------------------------------------- rules
def _finding(fid, category, priority, title, evidence, action, effort, impact, needs_approval=True):
    """This packages one growth-plan recommendation in a standard format."""
    return {'id': fid, 'category': category, 'priority': priority, 'title': title,
            'evidence': evidence, 'action': action, 'effort': effort,
            'expected_impact': impact, 'requires_approval': needs_approval}


BOT_NAMES = {'GPTBot': 'ChatGPT', 'OAI-SearchBot': 'ChatGPT search', 'ChatGPT-User': 'ChatGPT',
             'Google-Extended': 'Gemini', 'PerplexityBot': 'Perplexity', 'ClaudeBot': 'Claude',
             'anthropic-ai': 'Claude', 'CCBot': 'Common Crawl'}


def recommend(signals: dict, eval_detail: dict | None, facts: list[dict], business: dict) -> list[dict]:
    """This turns website signals and missed local searches into a ranked, plain-English growth plan."""
    out = []
    s = signals or {}
    name = business.get('business_name', 'your business')
    loc = business.get('location', 'your area')

    if s.get('ai_bots_blocked'):
        who = sorted({BOT_NAMES.get(b, b) for b in s['ai_bots_blocked']})
        out.append(_finding('GEO-CRAWL', 'visibility', 'high',
            'Let AI assistants read your website',
            f"Your website is set to block {' and '.join(who)} from reading it. So these assistants rely on outside listings, which may be outdated.",
            'Change one setting on your website to let AI search assistants in (your web person edits a file called robots.txt). We prepare the exact change.',
            '15 minutes', 'AI can quote your own website instead of old third-party pages.'))

    types = set(s.get('schema_types') or [])
    if not types & LOCAL_SCHEMA:
        out.append(_finding('GEO-SCHEMA', 'visibility', 'high',
            'Give AI a "digital business card"',
            'Your website is missing the standard behind-the-scenes business info (hours, address, menu, prices) that AI tools read most reliably.',
            'We generate it from your approved facts. Your web person pastes it into the site once (this is called schema.org structured data).',
            'About 1 hour', 'AI gets your facts straight from you, word for word.'))

    if s.get('menu_format') == 'pdf':
        out.append(_finding('GEO-MENU', 'accuracy', 'high',
            'Put your menu on your website as text, not a PDF',
            "Your prices are only in a PDF or image. AI tools often can't read those, so they use old menus from other sites.",
            'Add a simple menu page with item names and prices typed out.',
            '2 to 3 hours', 'Fewer wrong prices in AI answers.'))

    if not s.get('has_faq'):
        out.append(_finding('GEO-FAQ', 'visibility', 'medium',
            'Add a short FAQ page',
            "There's no page answering the questions customers ask AI (hours, delivery, reservations, catering).",
            'Publish short, direct answers. We wrote a first draft from your approved facts; review it before it goes live.',
            'About 1 hour', 'AI assistants love quoting short, clear answers.'))

    listings = s.get('listings') or {}
    site = listings.get('website', {})
    labels = {'hours': 'hours', 'delivery': 'delivery information'}
    for key in ('hours', 'delivery'):
        truth = site.get(key)
        wrong = [src for src, vals in listings.items() if src != 'website' and truth and vals.get(key) and vals[key] != truth]
        if wrong:
            places = ' and '.join(w.capitalize() for w in wrong)
            out.append(_finding(f'ACC-LISTING-{key.upper()}', 'accuracy', 'high',
                f'Your {labels[key]} are wrong on {places}',
                f"Your website says \"{truth}\", but {places} " + ('say' if len(wrong) > 1 else 'says') +
                f" \"{listings[wrong[0]][key]}\". AI assistants are repeating the wrong version.",
                f'Update your {labels[key]} on {places} to match your website.',
                '30 minutes', 'Removes the most likely source of this wrong answer.'))

    if s.get('google_profile_complete') is False:
        out.append(_finding('GEO-GBP', 'visibility', 'medium', 'Finish your Google Business Profile',
            'Your Google profile is missing details like categories, a menu link and services.',
            'Add your category, menu link, services (pickup, catering) and a few photos.',
            '45 minutes', 'Gemini and Google-based answers lean heavily on this profile.'))

    if s.get('review_count') is not None and s['review_count'] < 50:
        out.append(_finding('GEO-REVIEWS', 'visibility', 'medium', 'Get more honest customer reviews',
            f"You have {s['review_count']} reviews online. Competitors that AI recommends usually have more.",
            'Ask happy customers for a review (a QR code at the register works well). Never buy or fake reviews.',
            'Ongoing', 'More real mentions make AI more likely to recommend you.'))

    if not s.get('meta_description'):
        out.append(_finding('GEO-META', 'visibility', 'low', 'Add a one-sentence description to your homepage',
            "Your homepage doesn't have a short summary of who you are.",
            f'One sentence: what {name} is, where it is ({loc}), and what you are known for.',
            '10 minutes', 'Helps AI describe you correctly in one line.'))

    if not s.get('llms_txt'):
        out.append(_finding('GEO-LLMS', 'visibility', 'low', 'Optional: add an AI summary file',
            'Some AI tools look for a short summary file on websites (called llms.txt). This is new and not guaranteed to help.',
            'We can generate one that points to your menu, hours and FAQ.',
            '15 minutes', 'Low cost, possible upside. Treat it as an experiment.'))

    if eval_detail:
        products = {f['product_name'].lower(): f['product_name'] for f in facts if f['product_id'] != 'business'}
        for r in eval_detail.get('results', []):
            if r['type'] == 'visibility' and not (r.get('visibility') or {}).get('mentioned'):
                q = r['question'].lower()
                related = [n for k, n in products.items() if k in q]
                if 'catering' in q:
                    related.append('catering')
                out.append(_finding(f"GAP-{r['question_id']}", 'visibility', 'medium',
                    f"You're not showing up when people ask: \"{r['question']}\"",
                    'AI recommended other businesses instead of you.',
                    'Add a section to your website that answers this directly' +
                    (f" (mention your {', '.join(sorted(set(related)))})" if related else '') +
                    f' and say where you are ({loc}).',
                    '1 to 2 hours', 'Targets a real customer question where you are invisible today.'))

    if not s:
        # We haven't looked at the website yet, so don't guess about it: keep only the
        # steps that come from the check itself, and ask for the website.
        out = [f for f in out if f['id'].startswith('GAP-')]
        out.append(_finding('GEO-SITE', 'visibility', 'medium', "Let us check your website",
            "We haven't looked at your website yet, so this plan only covers the searches where you didn't show up.",
            'Enter your website in "Check any business website" below. We will check whether AI assistants can read it.',
            '1 minute', 'Adds website fixes (menu, business info, AI access) to your plan.', needs_approval=False))
    order = {'high': 0, 'medium': 1, 'low': 2}
    return sorted(out, key=lambda f: order[f['priority']])


# ---------------------------------------------------------------- drafts
def template_faq(facts: list[dict], business: dict) -> str:
    """This writes a simple FAQ from the business's approved facts."""
    name = business.get('business_name', 'We')
    lines = [f'{name}: Frequently asked questions', '']
    by = {(f['product_id'], f['field'], f['context']): f['value'] for f in facts if f['approved']}
    qa = [(('business', 'hours', ''), 'What are your hours?', lambda v: f'{v}.'),
          (('business', 'address', ''), 'Where are you located?', lambda v: f'{v}.'),
          (('business', 'policy', 'delivery'), 'Do you deliver?', lambda v: f'{v.capitalize()}.'),
          (('business', 'policy', 'reservations'), 'Do you take reservations?', lambda v: f'{v.capitalize()}.'),
          (('business', 'policy', 'catering minimum'), 'Do you cater?', lambda v: f'Yes, for groups of {v} or more.')]
    for key, q, a in qa:
        if key in by:
            lines += [q, a(by[key]), '']
    return '\n'.join(lines).strip()


def _schema(facts: list[dict], business: dict) -> str:
    """This builds the business info markup (schema.org) from approved facts,
    ready for a web person to paste into the site.
    """
    by = {(f['product_id'], f['field'], f['context']): f['value'] for f in facts if f['approved']}
    menu = [{'@type': 'MenuItem', 'name': f['product_name'] + (f" ({f['context']})" if f['context'] else ''),
             'offers': {'@type': 'Offer', 'price': f['value'], 'priceCurrency': 'USD'}}
            for f in facts if f['approved'] and f['field'] == 'price_usd']
    data = {'@context': 'https://schema.org', '@type': 'Restaurant', 'name': business.get('business_name'),
            'address': by.get(('business', 'address', ''), ''), 'openingHours': by.get(('business', 'hours', ''), ''),
            'url': business.get('website', ''), 'hasMenu': {'@type': 'Menu', 'hasMenuItem': menu}}
    return ('Paste this into your website\'s <head> (your web person will know where):\n\n'
            '<script type="application/ld+json">\n' + json.dumps(data, indent=2, ensure_ascii=False) + '\n</script>')


def _menu(facts: list[dict], business: dict) -> str:
    """This writes a plain text menu with prices from approved facts."""
    lines = [f"{business.get('business_name', '')} Menu", '']
    for f in facts:
        if f['approved'] and f['field'] == 'price_usd':
            ctx = f" ({f['context']})" if f['context'] else ''
            lines.append(f"{f['product_name']}{ctx} ........ ${float(f['value']):.2f}")
    return '\n'.join(lines)


DRAFTABLE = {'GEO-CRAWL', 'GEO-SCHEMA', 'GEO-MENU', 'GEO-FAQ', 'GEO-META', 'GEO-LLMS',
             'ACC-LISTING-HOURS', 'ACC-LISTING-DELIVERY'}


def can_draft(finding_id: str) -> bool:
    """This says whether a growth-plan step has a 'Write it for me' draft."""
    return finding_id in DRAFTABLE or finding_id.startswith('GAP-')


def draft_content(finding: dict, facts: list[dict], business: dict) -> dict:
    """This writes the draft fix for a step: exact templates for technical fixes (robots.txt,
    markup, menu), and Gemini for written content, using only approved facts. Drafts always
    need approval before anything is published.
    """
    fid = finding.get('id', '')
    name, loc = business.get('business_name', ''), business.get('location', '')
    by = {(f['product_id'], f['field'], f['context']): f['value'] for f in facts if f['approved']}
    fixed = None
    if fid == 'GEO-CRAWL':
        fixed = ('Add these lines to your website\'s robots.txt file so AI assistants can read it:\n\n'
                 '# AI search and answer assistants\n'
                 'User-agent: OAI-SearchBot\nAllow: /\n\nUser-agent: ChatGPT-User\nAllow: /\n\n'
                 'User-agent: PerplexityBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\n'
                 '# Optional: AI model training. Your choice; blocking these does not hide you from AI search.\n'
                 'User-agent: GPTBot\nAllow: /\n\nUser-agent: Google-Extended\nAllow: /\n\n'
                 '(Remove any "Disallow: /" lines for these names.)')
    elif fid == 'GEO-SCHEMA':
        fixed = _schema(facts, business)
    elif fid == 'GEO-MENU':
        fixed = _menu(facts, business)
    elif fid == 'GEO-LLMS':
        fixed = (f'# {name}\n> {business.get("category", "Local business")} in {loc}.\n\n'
                 f'- Menu and prices: {business.get("website", "")}/menu\n- Hours and location: {business.get("website", "")}/visit\n'
                 f'- FAQ: {business.get("website", "")}/faq')
    elif fid.startswith('ACC-LISTING-'):
        key = 'hours' if fid.endswith('HOURS') else 'delivery'
        truth = by.get(('business', 'hours', '')) if key == 'hours' else by.get(('business', 'policy', 'delivery'))
        fixed = (f'Log in to each listing and set your {key} to exactly:\n\n    {truth}\n\n'
                 'Tip: copy it word for word so every site matches your website.')
    if fixed is not None:
        return {'draft': fixed, 'source': 'template', 'status': 'needs_approval'}

    fallback = template_faq(facts, business)
    if fid == 'GEO-META':
        fallback = f'{name} is a {business.get("category", "local business")} in {loc}, open {by.get(("business","hours",""), "")}.'
    elif fid.startswith('GAP-'):
        q = finding.get('title', '')
        fallback = (f'Suggested website section for the question {q.split(":",1)[-1].strip()}\n\n'
                    f'At {name} in {loc}, ... [NEEDS OWNER INPUT: 2-3 sentences answering this question using your real menu and services]')
    approved = [{'item': f['product_name'], 'field': f['field'], 'context': f['context'], 'value': f['value']}
                for f in facts if f['approved']]
    if not os.getenv('GEMINI_API_KEY'):
        return {'draft': fallback, 'source': 'template', 'status': 'needs_approval'}
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        prompt = json.dumps({'business': business, 'finding': finding, 'approved_facts': approved}, ensure_ascii=False)
        resp = client.models.generate_content(
            model=os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite'), contents=prompt,
            config=types.GenerateContentConfig(system_instruction=(
                'You write short, friendly website copy for a small business owner to fix the finding described. '
                'Use ONLY the approved_facts; never invent prices, hours, offers or claims. '
                'If a needed fact is missing, write [NEEDS OWNER INPUT]. Plain text, no markdown symbols, under 150 words.'),
                temperature=0.3))
        text = (resp.text or '').strip()
        return {'draft': text or fallback, 'source': 'gemini' if text else 'template', 'status': 'needs_approval'}
    except Exception:
        return {'draft': fallback, 'source': 'template', 'status': 'needs_approval'}
