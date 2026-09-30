# Code guide: read it in this order

Every function in the code starts with a plain-English line that begins with "This…". This page tells you which file to open first.

| Order | File | What it does, in one sentence |
|---|---|---|
| 1 | `data/casa_coqui/` | The demo business: its approved facts (`catalog.csv`), the 20 locked questions (`questions.json`), the hand-written Week 1 and Week 3 AI answers, and its website signals (`profile.json`). **All synthetic.** |
| 2 | `app.py` → `api_eval_start()` / `api_eval_step()` / `run_one()` | Runs a check one question at a time so the dashboard can show each result and each new ticket live. (`run_eval()` does the same in one go for the demo seed and tests.) |
| 2b | `app.py` → `api_business_setup()` | Sets up a business from a CSV: imports approved facts, writes one question per fact (`accuracy_questions()`), and adds local-search and trick questions (Gemini or `template_questions()`). |
| 3 | `app.py` → `ask_gemini_shopper()` | The AI Mystery Shopper: asks Gemini with Google Search like a customer (live mode only). |
| 4 | `ai.py` → `extract_claims()` | Gemini pulls factual claims out of an answer; any claim without an exact quote is rejected. |
| 5 | `verifier.py` → `verify()` | Plain code decides CORRECT / INCORRECT / NEEDS_REVIEW / UNVERIFIABLE. No AI. `canonical_hours()`, `canonical_address()` and `canonical_policy()` let the same fact written in different words still match. |
| 6 | `app.py` → `process_answer()` and `flag_invention()` | Turns INCORRECT claims into tickets with a severity, and suspected made-up answers to trick questions into "AI may have made something up" tickets for a person to confirm. One ticket per wrong fact; an approved ticket is marked fixed only when a later answer is correct, and flagged "still wrong" when the AI repeats the error. |
| 7 | `scoring.py` | The formulas behind every number on the dashboard. |
| 8 | `geo.py` | The growth plan: real website check, rules that pick recommendations, and "Write it for me" drafts. |
| 9 | `evals.py` | Loads the question lists and demo answers; reads live answers for mentions and rank; measures our own extractor. |
| 10 | `models.py` | The exact data shapes we accept from Gemini and from users. |
| 11 | `static/audit.html` | The owner dashboard (display only). Wording for both languages lives in the `T` object. |

## What is hand-written vs. computed

- **Hand-written (synthetic):** the demo business, its facts, the 20 questions, the Week 1 / Week 3 AI answers and their labels, the website signals, and the automatic approvals between Week 1 and Week 3.
- **Computed by real code:** every verdict, ticket, severity, score, comparison, and growth-plan recommendation.
- **Live AI:** "Run a live check with Gemini", "Test our own checker", "Write it for me" (for written content when a key is set), and the real website check (no AI, but real data).

## The flow

Questions → AI Mystery Shopper → answer → (local search: mentioned? ranked?) or (business question: extract claims → verify) → correct / can't verify / wrong → ticket → human approve or reject → corrective action → retest → fixed, or back to review.
