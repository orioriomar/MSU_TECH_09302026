# Proof Flower 🌸

### Trustworthy AI Product Discovery for Small Businesses

**Montclair State University**  
**2026 HSI Battle of the Brains — Austin, Texas**

Proof Flower is a web-based platform that helps small businesses understand how they appear in AI-assisted shopping.

As consumers increasingly ask AI assistants questions such as *"Where should I eat?"* or *"What product should I buy?"*, businesses face two major risks:

- **Visibility:** The AI may never mention the business.
- **Accuracy:** The AI may provide incorrect information about the business, such as the wrong price, hours, availability, address, or policies.

Proof Flower audits how AI assistants represent a business, measures visibility and factual accuracy, detects potential hallucinations, creates actionable issue tickets, and allows businesses to re-test their AI presence after corrections.

> **Live Application:** `[ADD RENDER URL HERE]`

---

## Core Features

### 🔎 AI Mystery Shopper

Proof Flower uses realistic consumer questions to evaluate how an AI assistant represents a business.

Questions are divided into three categories:

- **Visibility** — Does the business appear in relevant AI recommendations?
- **Accuracy** — Are factual claims about the business correct?
- **Stress** — Does the AI confidently invent unsupported information?

The same locked question set can be reused across evaluations, allowing results to be compared over time.

---

### 📊 AI Visibility Monitoring

Proof Flower records whether a business appears in AI-generated recommendations and analyzes:

- Whether the business was mentioned
- Its position in a recommendation list
- Whether the business was recommended, mentioned neutrally, or framed negatively
- Overall inclusion rate

This allows businesses to measure whether changes to their online presence improve AI visibility.

---

### ✅ Fact Verification

Businesses provide verified information such as:

- Prices
- Product or menu availability
- Business hours
- Addresses
- Policies

Only approved facts are treated as authoritative.

Gemini extracts factual claims from AI-generated responses, but **Gemini does not determine whether those claims are true**.

Instead, deterministic Python verification compares extracted claims against the business's approved facts.

A claim receives one of four verdicts:

- `CORRECT`
- `INCORRECT`
- `NEEDS_REVIEW`
- `UNVERIFIABLE`

Only verified contradictions automatically generate discrepancy tickets.

---

### 🎫 Discrepancy Ticketing

When Proof Flower detects an incorrect factual claim, it creates a ticket containing information such as:

- The AI-generated claim
- The verified business information
- The affected product or business fact
- Supporting source
- Severity/priority
- Suggested corrective action
- Review status

Duplicate issues are updated rather than repeatedly creating new tickets.

Tickets can then be reviewed and approved by a human.

---

### 🔁 Re-Testing

Approving a correction does not automatically mean the problem has been solved.

Proof Flower can run the same evaluation again after corrective action.

If the AI now provides the correct information, the issue can be marked as verified.

If the AI continues providing the incorrect information, the ticket remains open.

This allows Proof Flower to measure whether corrective actions actually improved AI representation.

---

### 🌐 GEO Website Audit

Proof Flower also evaluates signals that may affect a business's visibility in AI-assisted discovery.

The website audit can inspect:

- AI crawler access through `robots.txt`
- Schema.org structured data
- FAQ content
- Menu format
- Business information on the page
- `llms.txt`
- Business hours
- Contact information

Proof Flower then creates a prioritized Generative Engine Optimization (GEO) growth plan based on the detected issues.

Recommendations may include improving structured data, making menus machine-readable, adding FAQ content, or allowing appropriate AI search crawlers to access the website.

---

## How Proof Flower Works

```text
                    BUSINESS
                       │
                       ▼
              Verified Business Data
                       │
                       ▼
              Approved Fact Catalog
                       │
                       │
Consumer Questions ───┼────► AI Mystery Shopper
                       │              │
                       │              ▼
                       │       AI-Generated Answer
                       │              │
                       │              ▼
                       │       Gemini Claim Extraction
                       │              │
                       └──────────────┤
                                      ▼
                            Python Fact Verification
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                      Correct                  Incorrect
                         │                         │
                         ▼                         ▼
                   Record Result          Create / Update Ticket
                                                   │
                                                   ▼
                                              Human Review
                                                   │
                                                   ▼
                                           Corrective Action
                                                   │
                                                   ▼
                                                Re-Test
                                                   │
                                                   ▼
                                           Measure Improvement
```

The architecture intentionally separates **AI interpretation** from **truth verification**.

AI is used for tasks where natural-language understanding adds value. Deterministic Python logic decides whether a factual claim matches approved business data.

---

## AI Health Metrics

Proof Flower measures multiple dimensions of a business's AI presence.

### Visibility Score

Visibility questions are scored using:

```text
(1 / rank) × framing
```

Framing weights:

```text
Recommended = 1.0
Neutral     = 0.6
Negative    = 0.2
Absent      = 0
```

---

### Inclusion Rate

```text
Businesses Mentioned / Visibility Questions × 100
```

This measures how frequently the business appears in relevant AI recommendations.

---

### Accuracy Score

Accuracy uses severity-weighted factual verification.

```text
1 - (Severity Weight of Incorrect Claims /
     Severity Weight of All Verifiable Claims)
```

Current severity weights include:

```text
Price        = 3
Policy       = 3
Availability = 2
Hours        = 2
Address      = 2
```

Unverifiable claims are not automatically counted as errors.

---

### Hallucination Rate

Stress questions measure whether the AI confidently provides unsupported or incorrect information.

```text
Hallucinated Stress Answers / Total Stress Questions × 100
```

An AI response that appropriately abstains when information cannot be verified is treated as safe rather than hallucinated.

---

### AI Trust Score

Proof Flower combines the major evaluation dimensions into an overall AI Trust Score:

```text
40% Accuracy
+ 35% Visibility
+ 25% Reliability
```

where:

```text
Reliability = 100 - Hallucination Rate
```

If a component is unavailable, the remaining weights are proportionally rebalanced.

---

## Technology Stack

### Backend

- **Python 3.12**
- **FastAPI**
- **Pydantic**
- **SQLite**

### Artificial Intelligence

- **Google Gemini**
- `google-genai`
- Gemini structured claim extraction
- AI-generated shopper questions
- Google Search grounding for live mystery-shopping evaluations
- Optional local **Ollama** fallback

### Website Analysis

- **Requests**
- **BeautifulSoup**
- `robots.txt` analysis
- Schema.org structured-data analysis
- Website AI-readiness checks

### Frontend

- Vanilla **HTML**
- **CSS**
- **JavaScript**

### Testing

- **pytest**
- FastAPI `TestClient`
- Automated tests covering scoring, verification, ticketing, evaluation, website auditing, business setup, and AI extraction behavior

### Deployment

- **Docker**
- **Render**

---

## Application Architecture

Proof Flower follows an ETL → Evaluate → Advise workflow.

### 1. Extract

Proof Flower collects:

- Human-approved business facts
- AI-generated shopper responses
- Website signals
- AI citations

### 2. Transform

Gemini converts natural-language AI responses into structured factual claims.

Pydantic validates the resulting data.

Claims must include supporting text from the original AI answer.

### 3. Load

Results are stored in SQLite, including:

- Business facts
- Questions
- AI responses
- Extracted claims
- Verification verdicts
- Tickets
- Evaluation runs
- Audit records

### 4. Evaluate

The same versioned question set can be reused over time to measure changes in:

- Visibility
- Inclusion
- Accuracy
- Hallucination rate
- Overall AI Trust Score

### 5. Advise

Proof Flower converts detected issues into:

- Accuracy tickets
- GEO recommendations
- Draft corrective content
- Re-testing workflows

---

## What Judges Should Do

The application is designed to be explored without requiring judges to install the project locally.

### 1. Open the Dashboard

Open:

`[ADD RENDER URL HERE]`

The main page displays the small-business owner experience.

---

### 2. Review the AI Health Score

Review the dashboard metrics for:

- Visibility
- Inclusion
- Accuracy
- Hallucination rate
- Overall AI Trust Score

---

### 3. Run an AI Check

Use the evaluation controls to run the business through the AI Mystery Shopper.

Proof Flower asks the evaluation questions, analyzes the responses, extracts factual claims, and checks them against approved business data.

---

### 4. Review Detected Issues

Open the issue/ticket section.

Review:

- What the AI said
- What the verified information says
- The discrepancy
- Severity
- Recommended corrective action

---

### 5. Review and Approve an Issue

Proof Flower keeps humans in control of corrective actions.

Review a ticket and approve or reject the proposed action.

---

### 6. Re-Test

Run the evaluation again after corrective action.

Proof Flower checks whether the AI still provides the incorrect information.

A correction is not considered successful simply because it was approved — the subsequent evaluation must confirm the improvement.

---

### 7. Review the Growth Plan

Explore the GEO recommendations generated from the business's website signals and visibility results.

---

### Analyst Console

A more technical interface is available at:

```text
/console
```

This view provides additional information for technical users and judges.

---

## Demo Data

Proof Flower includes a synthetic showcase business for demonstration purposes.

The showcase business and its associated AI responses are **synthetic and clearly labeled as demo data**.

Synthetic results are not presented as measurements of a real business.

The live evaluation mode uses Gemini to evaluate real responses using the same verification and scoring pipeline.

---

## Governance & Human Oversight

Proof Flower is designed around human-in-the-loop governance.

### Automatic Actions

Proof Flower can automatically:

- Run evaluations
- Extract claims
- Compare claims against approved facts
- Generate discrepancy tickets
- Update recurring issues
- Calculate metrics
- Generate draft recommendations
- Verify corrected issues during re-testing

### Human Approval Required

Human review is required before actions such as:

- Publishing website changes
- Changing verified business information
- Publishing AI-generated content
- Acting on sensitive price or policy recommendations
- Contacting external parties

Proof Flower does **not** automatically edit a business's live website or contact third parties.

---

## Data Integrity

Real business facts must be explicitly approved before Proof Flower treats them as authoritative.

Approved real-world facts require:

- A verified value
- An official HTTPS source
- A date indicating when the information was checked

This helps prevent unverified information from becoming the system's source of truth.

---

## Security Considerations

Proof Flower separates private configuration from the source code.

API keys are stored using environment variables and should never be committed to GitHub.

The included `.gitignore` excludes:

```text
.env
.env.*
*.sqlite3
.venv/
__pycache__/
.pytest_cache/
```

The application also restricts website-audit requests to public HTTPS resources to reduce the risk of accessing internal or private network resources.

---

## Running Proof Flower

### Hosted Version

The easiest way to evaluate Proof Flower is through the hosted application:

`[ADD RENDER URL HERE]`

No local installation is required.

---

## Running Locally

### Requirements

- Python 3
- Git
- Internet connection for live Gemini functionality

Clone the repository:

```bash
git clone https://github.com/orioriomar/HSIBOTB2026_Montclair.git
cd HSIBOTB2026_Montclair
```

Run:

```bash
./run.sh
```

The script:

1. Creates a Python virtual environment if needed
2. Installs the required dependencies
3. Creates `.env` from `.env.example` if needed
4. Starts the FastAPI application
5. Performs a health check

Then open:

```text
http://127.0.0.1:8000
```

The demonstration can run without a Gemini API key.

---

## Gemini Configuration

Live AI evaluations require a Gemini API key.

Copy the example environment configuration:

```bash
cp .env.example .env
```

Then configure:

```text
AI_PROVIDER=gemini
GEMINI_API_KEY=YOUR_PRIVATE_API_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
```

**Never commit `.env` or an API key to GitHub.**

---

## Docker

Proof Flower can also run in a Docker container.

```bash
./run.sh docker
```

The Docker configuration exposes the application on port:

```text
8000
```

---

## Running Tests

After activating the project's virtual environment:

```bash
source .venv/bin/activate
pytest -q
```

The automated test suite validates major functionality including:

- Fact verification
- Scoring calculations
- Visibility detection
- Hallucination handling
- Ticket creation
- Ticket deduplication
- Human approval
- Re-testing
- CSV business onboarding
- Website auditing
- AI claim extraction safeguards

---

## Project Structure

```text
HSIBOTB2026_Montclair/
│
├── app.py
│   Main FastAPI application, API endpoints, database,
│   evaluations, ticketing, and dashboard services
│
├── ai.py
│   Gemini/Ollama integration, question generation,
│   and factual claim extraction
│
├── verifier.py
│   Deterministic verification of AI claims against
│   approved business facts
│
├── scoring.py
│   Visibility, accuracy, hallucination, and
│   AI Trust Score calculations
│
├── evals.py
│   Evaluation sets, visibility parsing,
│   mock evaluations, and extractor metrics
│
├── geo.py
│   Website auditing and GEO recommendations
│
├── models.py
│   Pydantic data models and validation
│
├── static/
│   ├── audit.html
│   └── index.html
│
├── data/
│   Business facts, evaluation questions,
│   profiles, and demonstration data
│
├── tests/
│   Automated pytest test suite
│
├── docs/
│   Additional technical documentation
│
├── requirements.txt
├── render.yaml
├── Dockerfile
├── run.sh
├── .env.example
├── .gitignore
└── README.md
```

---

## Key Design Principle

Proof Flower separates **language understanding** from **truth determination**.

```text
Gemini:
"What factual claims did this AI response make?"

Python:
"Do those claims match the business's approved facts?"
```

This prevents the same AI system being evaluated from also serving as the final authority on whether its claims are correct.

When the system cannot confidently verify a claim, it can send the issue for review instead of automatically declaring it false.

---

## Future Development

Potential extensions include:

- Support for additional AI assistants
- Scheduled recurring evaluations
- Additional business categories
- Expanded product catalog integrations
- Historical trend analysis
- Automated alerts
- Additional GEO signals
- Multi-location business support
- Expanded reporting and analytics

The underlying evaluation architecture allows additional AI assistants to operate as new "mystery shoppers" while using the same verified facts, question sets, and scoring system.

---

## Team

**Montclair State University**  
**2026 HSI Battle of the Brains**

- Jose Acevedo
- Grace Velazquez
- Kimberly Escate
- Abel Molina
- Maximus Maurice-Okite
- Alison Ramos
- Omar Khattab
- Esperanza Baquedano

---

## Competition

**2026 HSI Battle of the Brains**  
**Challenge:** *The New Front Door: Trustworthy AI Product Discovery*

Proof Flower was developed to help small businesses remain **visible, accurately represented, and trusted** as consumers increasingly rely on AI assistants during the shopping journey.
