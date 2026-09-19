# Shipping Doc Checker

Hackathon prototype that triages a shipping-ops inbox and, for document-comparison
requests, checks a Shipping Instruction (SI) against a draft Bill of Lading (BL) on
7 fields: shipper, consignee, notify party, port of loading, port of discharge,
container count, and gross weight (kg).

This is scaffolding: the architecture is wired end-to-end, but classification,
extraction, and comparison currently use placeholder prompts/logic and need
refinement.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your keys:
   ```
   cp .env.example .env
   ```
   - `GEMINI_API_KEY` - required for classification and extraction (free tier available at [aistudio.google.com](https://aistudio.google.com/apikey))
   - `AWS_*` - only needed if you wire up `cloud/s3_client.py`

3. Sample inbox data is already in `data/` (`emails.json` + `attachments/`),
   loaded by `loader.py` at the project root.

4. Run the pipeline:
   ```
   python main.py
   ```
   This writes `output/submission.json` and submits it via `inbox.submit(...)`.

5. (Optional) View results in a browser:
   ```
   streamlit run app/viewer.py
   ```

6. Run tests:
   ```
   pytest
   ```
   The pipeline test is skipped automatically until `loader.py` is present.

## Project layout

- `src/classifier.py` - LLM email classification (document-comparison / new-SI-request / invoice-query / general / spam)
- `src/extractor.py` - LLM field extraction from SI/BL attachment text
- `src/comparator.py` - deterministic 7-field comparison, no AI
- `src/escalation.py` - deterministic missing-field / unreadable-attachment flagging, no AI
- `src/report.py` - assembles one report entry per email
- `src/pipeline.py` - orchestrates the above over the whole inbox
- `prompts/` - raw prompt text used by classifier.py / extractor.py
- `cloud/s3_client.py` - upload/download stubs, not yet wired into the pipeline
- `app/viewer.py` - minimal Streamlit table over `output/submission.json`
- `loader.py` - local inbox loader reading `data/emails.json` + `data/attachments/`

## Known gaps (by design, for now)

- Prompts in `prompts/` are rough first drafts.
- `src/pipeline.py` guesses which attachment is the SI vs. the BL by filename
  keywords - adjust `_find_attachment` once the real email/attachment schema
  from `loader.py` is known.
- No retry/backoff on LLM calls.
- `comparator.py` does exact-match comparison only (no normalization, e.g.
  "Ltd." vs "Limited").
