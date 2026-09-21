# Shipping document verification pipeline

Classifies 520 emails, then for `BL_COMPARISON` emails extracts 7 fields from the SI and BL, compares them deterministically, and escalates anything it cannot compare confidently.

## Setup

```
pip install -r requirements.txt
copy .env.example .env      # then set GEMINI_API_KEY
```

Data is read from `data/` (`inbox/*.json` + `attachments/`) through the provided `loader.py`. `ground_truth.json` is never read.

## Run

```
python main.py --limit 20 --out output/submission.json     # dev run
python main.py --workers 8                                  # full run
pytest tests
```

Every LLM response is cached under `.cache/llm/` (key = hash of model + prompt), so re-runs are free. `[llm] API calls made: N` prints on each real call.
Models (env-configurable): `CLASSIFY_MODEL` (cheap, `gemini-3.5-flash-lite`), `EXTRACT_MODEL` (`gemini-3.5-flash-lite`).

## Design

| Stage | File | Notes |
|---|---|---|
| Read | `src/readers.py` | txt/pdf/docx/xlsx -> text; raises `UnreadableAttachment` for 0-byte, truncated, scanned (no text layer) or garbled files |
| Classify | `src/classifier.py` | LLM; body is split from the quoted thread so the newest request decides |
| Extract | `src/extractor.py` | LLM; semantic label mapping is in `prompts/extract_prompt.txt`. Absent label -> `null`; present-but-blank (`???`, `____`, `TBA`, `N/A`) -> `"BLANK"` |
| Compare | `src/comparator.py` | pure Python: case/punctuation-insensitive names, port codes in brackets ignored, numeric equality |
| Escalate | `src/escalation.py` | precedence: missing_attachment > unreadable > wrong_doc_type > missing_value |

Wrong-document detection uses the document title deterministically, and skips extraction (saves calls).

## Assumptions to review

- `has_defect` is `true` only for `MISMATCH`; `NEEDS_REVIEW` entries get `false` (a blank/unreadable value is not a defect). One line to change in `src/report.py`.
- A `BL_COMPARISON` email with no attachments is `NEEDS_REVIEW / missing_attachment`.
- Party fields are compared on company name only, not addresses.
