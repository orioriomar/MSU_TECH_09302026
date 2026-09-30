# Proof Flower 🌸

### Trustworthy AI Product Discovery for Small Businesses

**Montclair State University | 2026 HSI Battle of the Brains**

Proof Flower helps small businesses understand **how AI assistants see them**.

When customers ask AI tools where to eat, what to buy, or which business to choose, two problems can occur:

- **Visibility:** The business may not appear in the AI response.
- **Accuracy:** The AI may give incorrect information about prices, hours, availability, addresses, or policies.

Proof Flower tests both, identifies problems, recommends fixes, and re-tests to see whether those fixes worked.

> **Live App:** `[ADD RENDER URL]`

---

## How It Works

```text
Business provides verified facts
            ↓
    AI Mystery Shopper
            ↓
    AI-generated answers
            ↓
 Gemini extracts claims
            ↓
Python verifies claims against
   approved business facts
            ↓
   ┌────────┴────────┐
 Correct          Incorrect
   ↓                 ↓
Record Result    Create Ticket
                     ↓
                Human Review
                     ↓
               Corrective Action
                     ↓
                   Re-Test
```

**Gemini extracts information — it does not decide what is true.**

Proof Flower uses deterministic Python logic to compare AI claims against human-approved business facts.

---

## Core Features

### 🔎 AI Mystery Shopper
Tests realistic shopping questions across three categories:

- **Visibility** — Does the business appear?
- **Accuracy** — Is the information correct?
- **Stress** — Does the AI invent unsupported information?

### 🎫 Discrepancy Tickets
Incorrect claims automatically create tickets showing:

- What the AI said
- The verified information
- The supporting source
- Issue priority
- Suggested corrective action

A human reviews changes before anything is acted on.

### 📊 AI Health Score
Proof Flower measures:

- Visibility
- Inclusion rate
- Factual accuracy
- Hallucination rate

These contribute to an overall **AI Trust Score**.

### 🌐 GEO Website Audit
Proof Flower can also inspect a business website for signals that may affect AI discovery, including:

- AI crawler access
- Schema.org structured data
- FAQ content
- Menu format
- Business information
- `llms.txt`

The system then creates a prioritized improvement plan.

### 🔁 Re-Testing
Proof Flower runs the same questions again after corrective action.

If the AI now provides the correct information, the issue can be verified. If the problem remains, the ticket stays open.

---

## Tech Stack

| Area | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | SQLite |
| AI | Google Gemini (`google-genai`) |
| Website Analysis | Requests, BeautifulSoup |
| Frontend | HTML, CSS, JavaScript |
| Testing | pytest |
| Deployment | Docker, Render |

---

## Architecture

Proof Flower separates **AI language understanding** from **truth verification**.

```text
Gemini
"What claims did this response make?"
        ↓
Python Verifier
"Do those claims match the approved facts?"
```

Claims receive one of four results:

- `CORRECT`
- `INCORRECT`
- `NEEDS_REVIEW`
- `UNVERIFIABLE`

Only verified contradictions automatically create discrepancy tickets.

---

## Try the Demo

1. Open `[ADD RENDER URL]`
2. Review the business's AI Health Score.
3. Run an AI check.
4. Watch Proof Flower evaluate the AI responses.
5. Open any generated discrepancy tickets.
6. Review the verified fact and suggested correction.
7. Approve or reject the ticket.
8. Re-test to see whether the issue was actually corrected.

A technical **Analyst Console** is also available at:

```text
/console
```

The included showcase business and its demonstration responses are **synthetic and labeled as demo data**.

---

## Run Locally

Clone the repository:

```bash
git clone https://github.com/orioriomar/HSIBOTB2026_Montclair.git
cd HSIBOTB2026_Montclair
```

Start the application:

```bash
./run.sh
```

Then open:

```text
http://127.0.0.1:8000
```

The demo works without an API key.

For live Gemini evaluations, create `.env` from `.env.example` and add:

```text
GEMINI_API_KEY=YOUR_PRIVATE_API_KEY
```

**Never commit `.env` or API keys to GitHub.**

### Docker

```bash
./run.sh docker
```

### Tests

```bash
source .venv/bin/activate
pytest -q
```

---

## Governance

Proof Flower uses a **human-in-the-loop** approach.

The system can automatically evaluate responses, verify claims, calculate metrics, and create tickets. Public-facing changes and modifications to verified business information require human approval.

Every decision can be recorded in the audit trail.

---

## Team

**Montclair State University — 2026 HSI Battle of the Brains**

Jose Acevedo · Grace Velazquez · Kimberly Escate · Abel Molina · Maximus Maurice-Okite · Alison Ramos · Omar Khattab · Esperanza Baquedano

---

## Challenge

**The New Front Door: Trustworthy AI Product Discovery**

Proof Flower helps small businesses stay **visible, accurately represented, and trusted** as AI becomes a new front door to shopping.
