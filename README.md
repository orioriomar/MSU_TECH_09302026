# Proof Flower 🌸

**Proof Flower checks what AI assistants tell customers about a small business, proves which facts are wrong against the owner's approved facts, turns each wrong fact into a correction ticket the owner approves, and re-asks the same questions to show whether the fix worked.**

Montclair State University · HSI Battle of the Brains 2026 · *"The New Front Door: Trustworthy AI Product Discovery"*
Esperanza Baquedano, Maximus Maurice-Okite, Omar Khattab, Kimberly Escate, Jose Acevedo, Abel Molina, Alison Ramos, Grace Velazquez

> **Live app: https://msu-tech-09302026.onrender.com**: opens straight into a complete demo. No login and no API key needed.
> The first load after a period of inactivity can take about a minute, because the free hosting plan sleeps.
> **Run it yourself:** `./run.sh` (Python) or `./run.sh docker`, then open http://127.0.0.1:8000

## How to Run

**Hosted:** Open the live link above. No installation is required.

### macOS / Linux

1. Download and unzip the project.
2. Open Terminal in the project folder.
3. Run:

```bash
./run.sh
```

4. Open `http://127.0.0.1:8000` in your browser.

### Windows

1. Download and unzip the project.
2. Open PowerShell in the project folder.
3. Run:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

4. Open `http://127.0.0.1:8000` in your browser.

### Docker (Windows, macOS, or Linux)

If Docker is installed, open a terminal in the project folder and run:

```bash
./run.sh docker
```

Then open `http://127.0.0.1:8000` in your browser.

**Note:** The demo works without an API key. Live AI checks require a Gemini API key.

---

## The Problem

Customers now ask ChatGPT, Gemini or Perplexity *"where should I eat?"* and act on a short answer. A small business can lose that customer in two ways, and never find out:

1. **The AI never mentions it** (visibility).
2. **The AI describes it wrong** (accuracy): an old price, wrong hours, "permanently closed", "they deliver" when they don't.

**The real case that started this project.** While researching local restaurants, our team asked an AI assistant about **Bistro Taíno**. It said **bacalaítos were not on the menu**, even though the restaurant's own menu listed them. A customer who believed that answer would simply go somewhere else. The owner would never know. `data/bistro_taino_TEMPLATE.csv` holds that business's facts as an *unapproved* template: the owner (or we, with a dated official source) must approve it before it can be used to call anything wrong.

## What Proof Flower does

| Step | What happens | Who does it |
|---|---|---|
| 1. **Approved facts** | The owner uploads a spreadsheet of facts (prices, hours, address, open/closed, delivery / reservations / catering policies). Only rows marked `approved = yes` with an official `https://` source and a checked date are treated as truth. | Owner |
| 2. **Locked question set** | One question per approved fact, plus local-search questions that never name the business, plus "trick" questions about offers that don't exist. The same set is re-used every check, so results are comparable. | Code (Gemini may draft the local-search and trick questions) |
| 3. **Mystery shopper** | Each question is asked like a customer would: Gemini with Google Search. | Gemini |
| 4. **Claim extraction** | Gemini turns each answer into structured claims, and **every claim must quote the answer word for word**. An invented quote or unknown product rejects the whole extraction, and no ticket is created. | Gemini → Pydantic → Python quote check |
| 5. **Verification** | Plain Python compares each claim with the approved fact: `CORRECT`, `INCORRECT`, `NEEDS_REVIEW` (ambiguous, e.g. lunch vs dinner price) or `UNVERIFIABLE` (no approved fact). **Only `INCORRECT` opens a ticket. Unknown is never called wrong.** | Code, no AI |
| 6. **Tickets** | One ticket per wrong fact, ranked Critical / High / Medium / Low, showing what the AI said, the approved truth, the AI's exact words, the page it cited and a next step. | Code |
| 7. **Human decision** | Approve fix / Look into it / Not an issue. Every decision is logged. Nothing is published or sent anywhere. | Owner |
| 8. **Growth plan (GEO)** | Rules turn website signals (AI crawler access in `robots.txt`, schema.org markup, FAQ, text vs PDF menu; listing consistency in the showcase profile) and missed local searches into ranked steps. **Check any business website** runs the crawler/schema/FAQ/menu audit on a real site. "Write it for me" drafts the fix from approved facts only. | Rules + Gemini drafts, owner approves |
| 9. **Re-check** | The same locked questions run again. A ticket closes **only** when the AI now gets that fact right. If the AI still repeats the error, the ticket stays open as *"approved, but AI still wrong"*. | Code |
| 10. **Before vs after** | Scores and every changed answer, question by question. | Code |

**Principle:** AI handles language, deterministic code decides what is true, and people approve anything consequential.

## Walkthrough Demo

The home page is written for a business owner (English / Español toggle, top right). The demo business, **Casa Coquí Café, is fictional and labeled "Sample data" on every screen**.

1. **Overview**: the AI health score, and four questions every owner asks: *Do customers find me? Does AI get my facts right? Does AI make things up? Did my fixes work?*
2. Click **Replay the demo from Week 1**. The check runs question by question, and each wrong answer is flagged and turned into a ticket live. One of them is the Bistro Taíno pattern: *"Casa Coquí Café's menu doesn't include bacalaítos."*
3. **Issues**: each ticket shows what AI tells customers vs the approved truth, the AI's exact words, the page it cited, and a next step. The Critical one: AI says the café is *permanently closed*. Click **Approve fix** on each.
4. **Growth plan** → **Write it for me** on "Put your menu on your website as text": the corrective action for the bacalaítos error.
5. Back on **Overview**, click **Run the Week 3 re-check (demo)**. It asks the same 20 questions: 7 fixes are confirmed. The **DoorDash delivery** ticket stays open, because the AI still repeats it. *An approved fix is not a working fix until a re-check proves it.*
6. **Questions** shows all 20 questions, the AI's exact answers, and what changed since Week 1.
7. **Our promise** covers what is automatic, what needs approval, what we never do, and how the score works, including **Test our own checker** (precision / recall of our extractor against hand-labeled answers; needs a Gemini key).

**Try a real business:** **+ Add a business** → download the template → fill it in → upload → **Run a live check with Gemini** (needs `GEMINI_API_KEY`).

### Showcase results (synthetic, recomputed by the code on every start)

| | Week 1 | Week 3 re-check |
|---|---|---|
| AI health score | **23** | **72** |
| Found in local searches | 2 of 6 | 5 of 6 |
| Facts the AI got right | 4 of 12 | 10 of 12 |
| Trick questions where AI made something up | 3 of 4 | 1 of 4 |
| Tickets | 8 opened | 7 confirmed fixed, 1 still wrong |

These answers were written by our team to demonstrate the workflow. The verdicts, tickets and scores computed from them are real code output (`tests/test_evals.py` checks them).

## Architecture

```
  Owner's approved facts (CSV)                     Locked question set (per business, versioned)
            │                                                   │
            ▼                                                   ▼
  ┌───────────────────┐   question   ┌──────────────────────────────────────────────┐
  │ SQLite: facts     │─────────────▶│ Mystery shopper: Gemini + Google Search      │  (demo: saved answers)
  └───────────────────┘              └──────────────────────────────────────────────┘
            │                                          │ answer + cited URLs
            │                                          ▼
            │                        ┌──────────────────────────────────────────────┐
            │                        │ Extractor: Gemini → JSON claims with quotes  │  AI (language only)
            │                        │ Pydantic schema + quote-must-exist + known   │  Python guardrails
            │                        │ product/field, else extraction FAILS         │
            │                        └──────────────────────────────────────────────┘
            │  approved facts                          │ claims
            └────────────────────────────────▶┌────────▼─────────────────────────────┐
                                              │ verifier.py: normalize + compare      │  deterministic
                                              │ CORRECT / INCORRECT / NEEDS_REVIEW /  │
                                              │ UNVERIFIABLE                          │
                                              └────────┬─────────────────────────────┘
                              INCORRECT only ▼                          ▼ all verdicts
                     ┌──────────────────────────────┐        ┌───────────────────────────┐
                     │ Ticket (one per wrong fact)  │        │ scoring.py: visibility,   │
                     │ → owner approves / rejects   │        │ accuracy, made-up rate,   │
                     │ → audit log                  │        │ AI health score           │
                     └──────────────┬───────────────┘        └───────────────────────────┘
                                    ▼
                     Re-check the same questions → CORRECT closes the ticket ("verified");
                     the same error again keeps it open ("approved, but AI still wrong")
```

### Where AI is used, and where it is not

| Task | Who | Why |
|---|---|---|
| Asking questions like a shopper | Gemini + Google Search | This *is* the thing being measured |
| Turning prose into structured claims | Gemini (`temperature=0`, JSON schema) | Language understanding; every claim must quote the answer exactly |
| Drafting local-search / trick questions and website copy | Gemini | Writing; drafts only, facts come only from the approved list |
| **Deciding if a claim is right or wrong** | **Python** (`verifier.py`) | Must be repeatable and auditable |
| Scores, tickets, severity, retest results | Python (`scoring.py`, `app.py`) | Anyone can recompute them by hand |
| Visibility (mentioned? rank? framing?) on live answers | Python text rules (`evals.py`) | Same answer → same result |
| Publishing anything, contacting anyone | **Nobody automatically.** An owner approves every public change | Governance |

### Scoring (`scoring.py`)

| Metric | Formula |
|---|---|
| Visibility | average over local-search questions of `(1 / rank) × framing`; framing: recommended 1.0, neutral 0.6, negative 0.2, not mentioned 0 |
| Inclusion rate | % of local-search answers that mention the business |
| Accuracy | `1 − Σ severity(wrong) / Σ severity(checkable)`; severity: price 3, policy 3, availability 2, hours 2, address 2. `UNVERIFIABLE` and `NEEDS_REVIEW` claims never count |
| Made-up rate | % of trick questions where the AI contradicts an approved fact or confidently says "yes" to an offer that isn't in the approved facts. "I'm not sure" is safe; an uncheckable claim is not counted as made up |
| **AI health score** | `0.40·Accuracy + 0.35·Visibility + 0.25·(100 − Made-up rate)`. Requires accuracy and visibility data; if only the trick-question part is missing, the other weights are rescaled |

**Honesty about the score.** The AI health score is **our internal composite for tracking one business over time**, not a validated industry index. The weights are a product decision, so the three parts are always shown next to it. A question the AI service failed to answer (quota, outage) is **excluded** from every score. A check where nothing could be answered is saved as *failed* and never replaces the last real result.

### Ticket severity

| Severity | When |
|---|---|
| Critical | AI says the business is closed when it is open |
| High | Wrong price, hours, address or policy |
| Medium | Wrong item availability (e.g. "bacalaítos aren't on the menu"); a suspected made-up offer (a person confirms) |
| Low | Anything else |

## Governance and accountability

- **Automatic:** asking the questions, extracting and verifying claims, opening and updating tickets, drafting fixes, and marking an approved ticket *verified* when a re-check gets the fact right.
- **Needs the owner's approval:** any change to a website or listing, anything about prices, policies or legal terms, contacting a third party, publishing AI-drafted text, and changing the approved facts. In this MVP, approval **records a decision**; nothing is published or emailed.
- **Never:** fake or incentivized reviews, hidden text or prompt tricks aimed at AI, disparaging competitors, calling a fix successful before a re-check shows it, or calling something *wrong* when we simply can't verify it.
- **Accountable:**
  - The business owner owns the approved facts and approves public changes.
  - The Proof Flower analyst owns the question set and the checker. As a process, they spot-check extractor output weekly and re-run **Test our own checker** after any prompt or model change.
  - Every decision is written to the audit log with a timestamp.
- **If our extractor is wrong:** a claim without a verbatim quote, or about an unknown product or field, is rejected and no ticket is created. An ambiguous value goes to `NEEDS_REVIEW`, never `INCORRECT`. Every ticket shows the AI's exact words so a person can catch a bad extraction before approving. The owner can mark it **Not an issue**, and the same fact will not reopen it.
- **Correlation, not causation:** a re-check that gets a fact right shows the AI's answer changed, not that our fix caused it. The audit log records it as *"retest observed, no causal claim"*.

## How this differs from GEO-monitoring tools (e.g. Peec AI)

Peec AI and similar tools measure *brand visibility and share of voice* for marketing teams. Proof Flower is built around **evidence-backed factual verification**:

- It compares each claim against the owner's approved, sourced facts, with deterministic code.
- It turns each wrong fact into a correction ticket with evidence and a next step.
- A person approves every correction.
- It re-tests the exact same question to prove whether the correction worked.

It is written for a non-technical owner (plain language, Spanish), and priced for small businesses rather than agencies.

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · SQLite · Google Gemini (`google-genai`, Google Search grounding) · Requests + BeautifulSoup (website audit) · vanilla HTML/CSS/JS (no build step) · pytest (41 tests) · Docker · Render.

| File | Role |
|---|---|
| `app.py` | API, pipeline (`process_answer`), check runner, tickets, report, demo seeding, CSV business setup |
| `verifier.py` | Deterministic normalization and comparison (prices, availability, hours, addresses, policies) |
| `scoring.py` | Every score formula (pure functions) |
| `evals.py` | Locked question sets, demo answers, live visibility parser, extractor precision/recall |
| `ai.py` / `models.py` | Gemini question drafting and claim extraction; strict schemas and guardrails |
| `geo.py` | Real website audit (robots.txt AI crawlers, schema.org, FAQ, menu format, llms.txt) with SSRF-safe fetching, GEO rules, drafts |
| `static/audit.html` | The dashboard (EN/ES): the only page, served at `/` |
| `data/casa_coqui/` | Synthetic showcase: approved facts, 20 locked questions, Week 1 and Week 3 answers, website signals |
| `tests/` | 41 tests, including governance rules (`tests/test_governance.py`) |


### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Enables live checks, question drafting, AI-written drafts and the extractor eval |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model for extraction, drafting and (by default) shopping |
| `GEMINI_SHOPPER_MODEL` | same as above | Optional separate model for the mystery shopper |
| `GEMINI_SEARCH_FALLBACK` | `1` | If the key has no Google Search quota, ask without web search and label the answer; `0` to fail instead |
| `LIVE_EVAL_DELAY` | `4` | Seconds between live calls (free-tier rate limits) |
| `SHOPPER_LOCATION` | `Paterson, NJ` | Default location for drafted local-search questions |
| `PROOF_FLOWER_DB` | `./proof_flower.sqlite3` | SQLite path (`/tmp/...` on Render) |
| `PROOF_FLOWER_SEED` | `1` | Load the Casa Coquí showcase on start |

### Tests

```bash
source .venv/bin/activate && pytest -q      # 41 passed; tests never call the real Gemini API
```
They cover:
- **Verdicts:** correct claim → no ticket; wrong claim → ticket; unverifiable → no accusation; ambiguous → needs review.
- **Guardrails:** invented quote or product → rejected.
- **Normalization:** price and availability parsing; an address without a ZIP is not called wrong.
- **Visibility:** ranking in lists and in prose.
- **Trick questions:** made-up classification ("unknown" is not "made up").
- **Ticket lifecycle:**
  - one ticket per wrong fact, even in new words;
  - approve and reject;
  - a re-check that is still wrong keeps the ticket open;
  - a re-check that passes marks it verified.
- **Failures:** quota stops a live check without scoring it or leaking provider text; search-quota fallback; the demo works with no key.
- **Security:** unsafe business IDs are rejected.

## Limitations

- **The showcase is synthetic.** Real results come only from live checks on a business you add.
- **One live assistant.** Live checks use Gemini's API with Google Search. That is not identical to what a consumer sees in the Gemini or ChatGPT apps. An OpenAI API route exists (`/api/run-live`, needs `OPENAI_API_KEY`) but is not in the dashboard. If Google Search quota is exhausted, answers come from the model without web search and are labeled.
- **Heuristic visibility.** The rank in prose answers is a text heuristic (lists are exact), and framing uses keyword rules.
- **Rule-based normalization.** Hours with different times on different days, price ranges and unfamiliar policy wording go to `NEEDS_REVIEW` instead of being guessed.
- **No login.** Anyone with the link can reset the demo or add a business. Production needs accounts and role-based approval.
- **Ephemeral storage.** SQLite on Render's free tier resets when the service restarts. Each visitor gets a private copy of the demo (remembered with a cookie), so one judge's clicks never change what another sees.
- **Spot checks are a process.** The weekly extractor spot check and risk-based cadence (daily for prices and policies) are designed but not automated.

## From MVP to production

- **Storage and accounts:** Postgres, accounts with owner and analyst roles, and approvals signed per user.
- **Scheduling and more assistants:** a scheduled job runner (weekly, and daily for price and policy facts). More assistants (ChatGPT, Perplexity, Claude, Copilot) plug in as extra "shoppers" behind the same question set and verifier.
- **Evidence and connections:** evidence snapshots of cited pages, plus Google Business Profile and menu connectors to keep approved facts current.
- **Quality monitoring:** extractor quality tracked per model version, with an alert when precision or recall drops.
