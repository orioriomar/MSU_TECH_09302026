**Gemini v3 note:** `AI_PROVIDER=gemini` is the default; `ai.py → call_gemini()` uses the `google-genai` Python SDK. The existing `call_ai()` name is preserved as a compatibility dispatcher. The `models.py` Pydantic classes remain the source of required output fields, and Python independently validates every model result.

# How to modify Proof Flower's two AI features

This is the quick reference for the teammate working on the models.

## A. The shopper question generator

**Where:** `ai.py` → `generate_questions()`. **Trigger:** `app.py` → `POST /api/questions/generate`. **Schema:** `models.py` → `QuestionSuggestion`, `QuestionBatch`.

1. Import the business's verified catalog through the app.
2. User chooses a business and the number of each question type.
3. Backend sends the business name and *approved fact descriptors* to Ollama through the configured provider (`Gemini` by default or optional `Ollama`).
4. The requested JSON schema is `QuestionBatch.model_json_schema()`. The prompt defines three types: `visibility`, `accuracy`, `stress`.
5. Pydantic and Python reject duplicate questions, unknown products, invalid fields, or brand-named generic discovery prompts.
6. Accepted questions get unique IDs and are stored in SQLite. They remain editable by deleting and replacing before a test run.

**Change the question style:** edit only the `system` prompt in `generate_questions()`. **Change the required JSON format:** edit `QuestionSuggestion` in `models.py` and adjust validation in `generate_questions()`.

```python
# The essential call already present in ai.py:
raw = call_ai(system, prompt, QuestionBatch.model_json_schema())
batch = QuestionBatch.model_validate(raw)
```

## B. The answer formatter / claim extractor

**Where:** `ai.py` → `extract_claims()`. **Trigger:** `app.py` → `process_answer()` after a pasted or live answer. **Schema:** `models.py` → `ExtractedClaim`, `ClaimBatch`.

For an answer such as *"No, Bistro Taíno does not currently serve Bacalaitos"*, the local model should return:

```json
{
  "brand_mentioned": true,
  "claims": [
    {
      "product_id": "bacalaitos",
      "field": "availability",
      "value": "unavailable",
      "context": "",
      "quote": "does not currently serve Bacalaitos"
    }
  ]
}
```

The model is **not told which answer is right**. After extraction, the backend validates the entire JSON object and confirms that `quote` is a literal substring of the answer and that every `(product_id, field)` exists in the catalog. If validation fails, the raw answer is saved as `failed` and no tickets are generated.

Then `verifier.py` finds the unique *approved* `(product_id, field, context)` fact. It compares normalized values with regular Python (`Decimal` for prices). Only `INCORRECT` verdicts create or update tickets.

**Change the extraction instructions:** edit the `system` prompt in `extract_claims()`. **Add new catalog fields:** update `FieldName` in `models.py`, `VALID_FIELDS` in `app.py`, and normalization in `verifier.py`; then add tests.

```python
# The key call already present in ai.py:
raw = call_ai(system, prompt, ClaimBatch.model_json_schema())
batch = ClaimBatch.model_validate(raw)
```

## C. If we want a second LLM later

The question generator and claim extractor both currently use `OLLAMA_MODEL`, so **one AI model is enough**. You can separately configure them later by adding `OLLAMA_QUESTION_MODEL` and `OLLAMA_EXTRACTION_MODEL` environment variables and passing a `model` argument into `call_ai()`. No second model is needed to decide factual accuracy; in fact, an LLM should not be the sole authority for factual truth.

## D. A safe demo when Ollama is offline

Run the synthetic demo first and verify that the ticket appears. Then paste a genuine answer and use the **manual claim** dropdown. This exercises the same `verifier.py` and ticket trigger. Do not claim this tests real Ollama extraction; it is a fallback for judges without Ollama installed.
