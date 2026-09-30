# Proof Flower 🌸 — AI Mystery Shopper

An original, **hackathon MVP** for investigating how AI shopping assistants represent small businesses. The app collects actual AI answers (pasted manually or via an optional Gemini or OpenAI web-search API call), formats product claims with **Gemini (or optional Ollama)**, compares them to a **human-reviewed CSV catalog**, and opens **standardized tickets** for confirmed mismatches. The dashboard has Approve / Reject / Investigate buttons and an audit trail.

**Honesty first:** Juniper Neighborhood Bakery and its answers are synthetic examples. The provided Bistro Taíno CSV is an **unapproved template** based on our preliminary investigation, NOT a claim that its sample prices are independently verified at deployment time. Real accuracy metrics exclude synthetic answers. Approval **does not publish content or email anyone**. A later matching answer is recorded as a retest, not proof that our intervention caused a third-party model to change.

## Connect Gemini (recommended—no Ollama download)

1. In Terminal, navigate to the extracted `proof_flower` folder and run `cp .env.example .env`.
2. Open `.env` in any text editor. Replace `PUT_YOUR_KEY_HERE` with your Gemini API key. **Never send the key in chat or commit it to GitHub.** `.gitignore` excludes `.env`.
3. From the project folder run `chmod +x run.sh && ./run.sh`. This installs `google-genai`, `python-dotenv`, and the app's other dependencies. If you had an older version running, stop it using Control-C before starting v3.
4. Open `http://127.0.0.1:8000`. Sidebar should say **Gemini configured** (this checks only that a key is present). In **Question generator**, choose a business and click Generate questions. Or in **Test answers**, paste a saved real response, select **Gemini AI formatter**, and click Check answer.
5. Optional: select a question and click **Run ONE live Gemini question**. This queries Gemini with Google Search grounding (subject to account tier and quotas), then sends the answer through the same claim extractor, fact checker, and ticket workflow. Gemini API answers are *not* consumer ChatGPT answers.

If the formatter reports a failed extraction, Proof Flower preserves the original answer and **does not create a ticket**. Review approved catalog facts and exact quotations first. You can always use manual extraction as a fallback. The app uses `gemini-2.5-flash-lite` for formatting and question generation by default and `gemini-2.5-flash` for grounded shopping tests; change these in `.env` if your key supports different models. API access and free-tier quotas vary.

For future hosting, add `GEMINI_API_KEY` as a private Vercel environment variable; never expose it to browser JavaScript. The existing local SQLite database does not persist reliably on Vercel—you'll need managed database storage for reviewer decisions before a publicly hosted production-style deployment.

## Start on your Mac (5 minutes)

1. Download the ZIP and extract it. Open Terminal in the extracted `proof_flower` folder.
2. Install Python 3 if necessary. Check with `python3 --version`.
3. Run the app:

   ```bash
   chmod +x run.sh
   ./run.sh
   ```

   If you've already created a virtual environment and want to avoid the install step:

   ```bash
   source .venv/bin/activate
   python3 -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
   ```

4. Visit **http://127.0.0.1:8000**. Click **Run sample demonstration** and open its clearly labeled synthetic discrepancy ticket.

`run.sh` deliberately uses `python3`, not `python`, to work with modern macOS installations. The first launch needs internet access to install pip dependencies; the synthetic demo works locally afterward.

## Optional: Add Ollama instead of Gemini (not required)

Install Ollama for macOS from [ollama.com/download](https://ollama.com/download). In a **second Terminal window**:

```bash
ollama pull llama3.2
ollama list
```

If choosing Ollama, set `AI_PROVIDER=ollama` in `.env` and restart Proof Flower. The Ollama desktop app normally starts its local server automatically. If you installed the CLI without the app or Ollama isn't running, use `ollama serve` in the second Terminal window. The default API endpoint is `http://127.0.0.1:11434/api/chat`. Reload Proof Flower. The sidebar should say *Ollama running* and show the installed model.

To use another installed model, set `OLLAMA_MODEL` **before starting** Proof Flower, e.g. `export OLLAMA_MODEL=llama3.1:8b`. Smaller models fit memory-constrained laptops but may extract facts less reliably; review their output.

### Where the two AI features live

`ai.py` contains exactly two AI workflows (Gemini by default, optional Ollama):

- **`generate_questions()`**: receives only the business name and approved product descriptors; requests visibility questions, product accuracy questions, and uncertainty/stress questions using `QuestionBatch.model_json_schema()`.
- **`extract_claims()`**: receives a saved AI answer, its original question, the business name, and catalog field descriptors; requests **exactly quoted claims** using `ClaimBatch.model_json_schema()`.

`models.py` defines the strict Pydantic schemas for both tasks. The configured model is instructed to return those shapes with temperature zero, and Python validates the result again. An answer containing an invented quotation or unknown product/field is saved with a **failed extraction** status and **cannot create a ticket**. The model is a *formatter*, not the authority on what is true.

The deterministic comparison is in `verifier.py`; the ticket-creation trigger is in `app.py` under `process_answer()`. It is simply:

```python
result = verify(claim, approved_catalog_facts)
if result['verdict'] == 'INCORRECT':
    # Find a matching open ticket, or create a new standardized ticket.
```

The database columns, not the AI formatter, define the ticket headers. An error ticket always carries: business, product, field, context, AI value, verified value, catalog fact ID, official source, suggested action, original answer, status, occurrence count, and timestamps. Evidence URLs and human decisions are recorded separately. Multiple copies of the same error increment the existing open ticket's occurrence count.

## Try our real-case workflow: Bistro Taíno

**1. Verify the menu facts.** From the **Verified catalog** tab, download `bistro_taino_TEMPLATE.csv`. Its starter rows contain Bacalaitos availability and price plus Carne Frita lunch/dinner prices from our earlier investigation. Check the restaurant's **currently applicable** official menus. Fill in each official `https://` source URL, set `checked_at` to the date *you* verified it, and set `approved=yes` only after reviewing the exact item, serving/ordering context, and price. An uncertain row should remain `approved=no`. CSV is your editable spreadsheet; the app imports the same CSV directly into SQLite. **Do not treat the initial template as verified evidence.**

**2. Import it.** In the **Verified catalog** tab choose the revised CSV and click **Import reviewed CSV**. Rows marked draft are visible but cannot prove an AI answer incorrect.

**3. Add questions.** In **Question generator**, select Bistro Taíno, specify the numbers of visibility / accuracy / stress questions, and click **Generate questions**. Edit by deleting unsuitable suggestions and adding your own questions. If Gemini is not yet configured, use the manual question form. For instance: *Does Bistro Taíno serve Bacalaitos?*

**4. Test actual assistants.** Ask the question in ChatGPT or another assistant with its normal shopping/search configuration. In **Test answers**, select the same question ID, paste the exact answer, and paste the AI's cited URLs (one per line). Click **Check answer and create tickets**. Gemini extracts claim(s) and Python checks them. You can also select **manual claim** to demonstrate the same Python verifier without Ollama. A manual claim requires a literal quotation from the supplied answer; not merely a paraphrase.

**5. Inspect and review.** Open **Review tickets**. A ticket is created for a claim that conflicts with one unique approved fact in exactly the same context. The dashboard shows the original answer and its cited URLs. You can click **Inspect cited page** for accessible ordinary HTML citations. This does *not* establish that the AI relied on the cited page. Review the suggested correction and choose Approve, Reject, or Investigate with a note. This MVP does not contact the publisher or change any real page.

**6. Retest.** After an authorized correction happens *outside this MVP*, rerun the same question. Paste the fresh answer as a new test. If an approved ticket's exact product/field/context now matches an approved catalog fact, it becomes **verified on retest**. This shows the observed difference; it does not assert causation.

### What counts as an error?

- **Correct:** An extracted claim equals the one approved fact for the same product, field and context.
- **Incorrect:** An extracted claim conflicts with that exact approved fact → automatically create / update a ticket.
- **Needs review:** The answer does not identify a unique applicable context, such as lunch versus dinner. No false error ticket is opened.
- **Unverifiable:** The company has no approved matching catalog fact. An unlisted item is **not automatically unavailable**.
- **Stress questions:** Test whether an assistant invents unsupported promotions or policies. Unsupported statements need human investigation; missing database fields do not automatically prove a hallucination.

## Optional: collect official public website text

The script below fetches **one** public official HTTPS webpage you are permitted to access. It saves a text snapshot and tries to create a **draft CSV** only if the page already has schema.org Product/Offer JSON-LD. It will not bypass access restrictions, scrape a whole site, read image-only menus, or mark scraped facts as verified.

```bash
python3 scripts/scrape_menu.py 'https://OFFICIAL-BUSINESS.example/menu' \
  --business-id=bistro_taino --business-name='Bistro Taíno'
```

The script writes `data/snapshots/*.txt` and sometimes `*_DRAFT.csv`. If the page has only unstructured menu text or images, a teammate should fill out the CSV template manually. **Don't blindly publish AI-extracted facts as source of truth.**

## Optional: one live OpenAI shopping answer

In the Terminal **before starting** the app:

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'
export OPENAI_MODEL='gpt-4.1-mini'
./run.sh
```

In **Test answers**, select a question and click **Run one live ChatGPT API question**. One paid OpenAI Responses API request uses `web_search` and captures citation URL annotations. Gemini (or your configured provider) then formats the answer; an extraction failure saves the raw response but creates no tickets. **Never commit your key, `.env`, or the local SQLite file.** This is API model behavior, not proof that all consumer ChatGPT accounts behave identically.

## Optional source inspection: what it can and cannot prove

The reviewer can manually retrieve the cited page. The local-only source inspector supports publicly accessible HTTPS HTML, no redirects, a 1 MB maximum, and public IP checks. It cannot prove the source caused the model's answer; dynamic pages, PDFs, blocked sites and inaccessible content require manual review. **Do not publish this local unauthenticated inspector directly to the internet without authentication, rate limiting, stronger network egress controls and robust security review.**

## Key files

| File | Purpose |
|---|---|
| `ai.py` | Gemini question generation and claim formatting, optional Ollama fallback (edit prompts here). |
| `models.py` | Required JSON fields and Pydantic validators for AI-generated inputs. |
| `verifier.py` | Python-only comparison with reviewed product facts. |
| `app.py` | FastAPI endpoints, SQLite storage, ticket trigger, audit and optional OpenAI adapter. |
| `static/index.html` | Responsive dashboard, CSV import, question generation, paste-answer UI and ticket queue. |
| `data/demo_catalog.csv` | Fictional approved demo catalog. |
| `data/bistro_taino_TEMPLATE.csv` | **Draft** real-business starter spreadsheet; verify before approving. |
| `scripts/scrape_menu.py` | Fetch one official HTML webpage, preserve a dated snapshot, export optional draft CSV. |
| `tests/test_flow.py` | Offline end-to-end tests including fake Ollama responses, ticket deduplication and retests. |

## Tests

```bash
source .venv/bin/activate
pytest -q
```

Unit/integration tests mock model responses, so they **do not** prove that your Gemini account/model produces accurate extraction on every real answer. Test representative real answers manually before your live pitch.

## Data and deployment

- `proof_flower.sqlite3` is created on first start. This is local application data, not persistent Vercel storage.
- The dashboard should not be publicly exposed as is: it has no production authentication or permission controls.
- Local Ollama on your Mac is **not** reachable from a Vercel deployment. For public hosting, Gemini is already hosted; add an authenticated reviewer system, safe source fetching, and managed database storage.
- The real business's public facts remain its responsibility; Proof Flower makes verification and correction auditable, not a guarantee of recommendations or increased sales.

## References (implementation guidance)

- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama local API](https://docs.ollama.com/api)
- [OpenAI Responses API — web search](https://developers.openai.com/api/docs/guides/tools-web-search)

- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API key guide](https://ai.google.dev/gemini-api/docs/api-key)
