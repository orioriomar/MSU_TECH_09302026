# Proof Flower 🌸 — AI-powered consulting for the new front door of shopping

Customers now ask AI assistants "where should I eat?" or "what laptop should I buy?" and act on a short answer. A small business can lose that customer in two ways: **the AI never mentions it** (visibility) or **the AI describes it wrong** (accuracy: wrong price, wrong hours, invented policies).

**Proof Flower audits how AI assistants see a business, scores it, and hands back a prioritized fix list.**

- **Accuracy problems → severity-ranked fix tickets** (Critical / High / Medium / Low). Every wrong claim is shown next to the verified fact, with the source the AI cited and a suggested correction. A human approves before anything changes.
- **Visibility gaps → a GEO action plan.** Rules read the website's AI-readiness signals (crawler access, schema.org, FAQ, menu format, listing consistency) plus the questions where the business was invisible, and produce ranked recommendations. Gemini drafts the content from approved facts only.
- **Re-test → proof.** The same locked question set runs again, and the scorecard shows what moved.

> **Live app:** `<ADD YOUR RENDER URL HERE>` · Opens straight into a complete, clearly labeled demo audit. No login, no setup.

---

## Try it with your own business (real AI, real flagging)

1. Click **+ Add a business** in the sidebar and download the spreadsheet template.
2. Fill in one row per fact (prices, hours, address, open/closed, delivery / reservations / catering policy). Only rows with `approved = yes` are used; real facts need the official `https://` page and the date you checked it.
3. Upload it, enter the city and type of business, and click **Set up business**. proof flower writes one question per approved fact, plus local-search and trick questions (Gemini, or templates if no key).
4. On **Overview**, click **Run a live check with Gemini**. Each question is asked live (Gemini + Google Search), the answer's claims are extracted, checked against your facts, and any contradiction is **flagged and turned into a ticket on the spot** in the live feed. A confident "yes" to a trick question (e.g. a Monday happy hour that isn't in your facts) is flagged too, as a Medium "AI made something up" ticket.

Needs `GEMINI_API_KEY` in `.env` (locally) or in Render's environment settings (hosted).

## What the judge should look at (3 minutes)

The home page is written for a small-business owner (English/Spanish toggle, top right). Technical detail lives in "How your score works" at the bottom and in the Analyst view (`/console`).

0. **Run a check** (Overview) — click it on the demo business to watch every question get asked and every wrong answer get flagged into a ticket, live. Approve the tickets, then run the Week 3 re-check to see which fixes are confirmed.
1. **AI health score** — before vs. after one fix cycle. Demo: AI health score **24 → 72**, found in **2 → 5 of 6** local searches, facts right **4 → 9 of 11**, made things up in **3 → 1 of 4** trick questions.
2. **What needs your attention** — issues ranked Critical / High / Medium / Low. The critical one: AI told customers the café was *permanently closed*.
3. **Being re-checked** — the DoorDash delivery issue: approved, but the AI still repeated the error on re-test, so it **stays open**. An approved fix is not a successful fix until the eval proves it.
4. **Your growth plan** — ranked GEO steps in plain language. **Write it for me** produces the real fix (robots.txt lines, schema.org markup, menu text, FAQ) from approved facts only. Paste any real website into **Audit a real website** to run the live crawler-access/schema/FAQ check.
5. **What customers see when they ask AI** — all 19 questions, the AI's exact answers, and what changed since the first check.
6. **How your score works** — the formulas, plus **Test our own checker**: we evaluate our own AI's precision/recall against hand-labeled answers.
7. **Our promise** — what's automatic, what needs approval, what we never do, and who is accountable.

**Honesty note:** the showcase business *Casa Coquí Café* (Paterson, NJ) and its AI answers are **synthetic** and labeled as such everywhere. **Live mode** ("Run live eval") asks Gemini with Google Search grounding the same questions and scores the real answers with the same code.

---

## How it works: ETL → Eval → Advise

```
EXTRACT     approved facts (website / CSV, human-approved)      AI answers (mystery shopper: Gemini + Google Search, or mock)
TRANSFORM   Gemini formats answers into claims → Pydantic validates → quotes must exist verbatim in the answer
LOAD        runs · claims · verdicts · tickets · eval_runs (SQLite; every score recomputable)
EVALUATE    locked, versioned question set (visibility / accuracy / stress) → deterministic scorecard
ADVISE      accuracy → fix tickets (human approval)   ·   visibility → GEO rules + drafted content (human approval)
```

**AI is used where it adds value** (drafting questions and content, turning prose into structured claims). **Python decides what's true** by comparing claims with approved facts. **Humans approve** anything public.

### The formulas (`scoring.py`)

| Metric | Formula |
|---|---|
| Visibility | average over visibility questions of `(1 / rank) × framing` · framing: recommended 1.0, neutral 0.6, negative 0.2, absent 0 |
| Inclusion rate | % of visibility answers that mention the business |
| Accuracy | `1 − Σ severity(wrong) / Σ severity(verifiable)` · severity: price 3, policy 3, availability 2, hours 2, address 2 · unverifiable claims never count as errors |
| Hallucination rate | % of stress answers that assert something unsupported or wrong (abstaining = safe) |
| **AI Trust Score** | `0.40·Accuracy + 0.35·Visibility + 0.25·(100 − Hallucination rate)` (renormalized if a part is missing) |

### Two evals
1. **Assistant eval**: grades the AI assistant on a fixed question set, so runs are comparable over time.
2. **Extractor eval** (`POST /api/evals/extractor`): grades *our own* Gemini extractor against hand-labeled answers (precision, recall, exact match).

---

## Tech stack

Python 3.12 · FastAPI · Pydantic · SQLite · Google Gemini (`google-genai`, Google Search grounding) · Requests + BeautifulSoup (site audit) · vanilla HTML/JS/CSS front end · pytest (19 tests) · Docker / Render.

| File | Role |
|---|---|
| `app.py` | API, ETL pipeline, eval runner, tickets, report, demo seeding |
| `scoring.py` | All score formulas (pure functions) |
| `evals.py` | Locked eval sets, mock assistant, live visibility parser, extractor metrics |
| `geo.py` | Real website audit (robots.txt AI-crawler check, schema.org, FAQ, llms.txt) + GEO rules + drafts |
| `ai.py` / `models.py` | Gemini question generation & claim extraction, strict schemas |
| `verifier.py` | Deterministic fact comparison |
| `static/audit.html` | Owner dashboard (home page, EN/ES) · `static/index.html` = analyst console (`/console`) |
| `data/casa_coqui/` | Showcase catalog, locked question set, baseline & re-test answers, site profile |

---

## Run it

**Hosted:** open the live link above.

**Locally (macOS/Linux):**
```bash
./run.sh            # creates .venv, installs, starts http://127.0.0.1:8000
./run.sh docker     # or build and run the container
```
The demo works **without** an API key. For live mode, put your key in `.env` (`GEMINI_API_KEY=...`). Never commit `.env`.

**Tests:** `source .venv/bin/activate && pytest -q`

**Deploy (Render, free):** New → Blueprint → select this repo (uses `render.yaml`) → set `GEMINI_API_KEY` as a secret env var. The app seeds the showcase on startup, so the hosted report is never empty.

---

## Governance & accountability

- **Automatic:** run evals, extract/verify claims, open/update tickets, draft fixes, mark tickets verified on a passing re-test.
- **Needs approval:** public website/listing changes, anything about price/policy/legal, contacting third parties, publishing AI drafts, changing the verified catalog.
- **Never:** fake or incentivized reviews, hidden text or prompt tricks aimed at AI, disparaging competitors, treating an unlisted item as unavailable, claiming a fix *caused* an AI change.
- **Accountable:** the business owner owns the verified catalog and approves public changes; the Proof Flower analyst owns the eval set and spot-checks 5% of extractor verdicts weekly; every decision is logged in the audit trail.
- **Scaling:** risk-based cadence (top sellers and price/policy facts daily, the rest weekly); each new AI assistant is another "shopper" behind the same eval set.

More detail: `docs/MVP_NOTES.md`, `docs/CONNECT_GEMINI.md`, `docs/HOW_TO_EXTEND.md`.
