# Connect Gemini to Proof Flower

> **Note:** this page describes the analyst console (`/console`) and earlier development steps. The [README](../README.md) is the authoritative, current description of the product and the owner dashboard.

**Do not share your key** with ChatGPT, teammates in screenshots, or GitHub. `.env` is excluded by `.gitignore`.

## One-time setup on your Mac

```bash
cd ~/Downloads/proof_flower
cp .env.example .env
open -e .env
```

Paste your own Gemini API key after `GEMINI_API_KEY=` in `.env`, save and close TextEdit. The file should include:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=your-private-key-here
GEMINI_MODEL=gemini-3.5-flash-lite
# GEMINI_SHOPPER_MODEL=gemini-3.5-flash   (optional)
```

Back in Terminal:

```bash
chmod +x run.sh
./run.sh
```

Open http://127.0.0.1:8000. The left sidebar should say `Gemini configured`. This only checks the presence of the key; an actual model call verifies access.

## First live test

1. On **Question generator**, select `Juniper Neighborhood Bakery` and ask for 1 visibility question and 1 accuracy question. Click **Generate questions**. You can also import a reviewed Bistro Taíno CSV under **Verified catalog** first if you'd prefer a real business.
2. Click **Test answers**. Choose one of the generated questions. Paste a real AI answer, select **Gemini AI formatter**, and click **Check answer and create tickets**.
3. Alternatively, click **Run ONE live Gemini question** to use Gemini for a web-grounded shopping answer *and* formatting. Gemini's model/API answers are not consumer ChatGPT answers, and Google Search grounding may be unavailable or limited on some accounts.
4. Check **Review tickets**. Python only creates a confirmed discrepancy ticket against a matching, approved catalog fact. If the formatter says `failed`, review its error and try again or use the manual extraction fallback.

The sample demonstration uses fictional responses. Do not present synthetic fixture results as live model evidence. Human ticket approval records a decision; it does not publish website changes.

## Deployment

The app is deployed with Render (`render.yaml`) or Docker (`./run.sh docker`). Set `GEMINI_API_KEY` as a secret environment variable, never in code. SQLite on Render's free tier lives in `/tmp` and resets on restart; see the README's limitations section.
