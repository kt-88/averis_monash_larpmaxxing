# Project overview: shipping document verification

Last updated: 2026-09-20. Read this first if you are new to the project or have been away from it.

## 1. What the system does

A shipping team's inbox gets document-check requests, new shipping-instruction (SI) requests, invoice questions, general updates and spam. This system:

1. **Classifies** every email (five categories, plus a finer "intent" and a plain-English title).
2. For document-check emails, **extracts** seven fields from the SI and the draft Bill of Lading (BL): shipper, consignee, notify party, port of loading, port of discharge, container count, gross weight (kg).
3. **Compares** them (the SI is the reference) and reports which fields differ, SI and BL side by side.
4. **Escalates to a person** when it cannot decide (missing attachment, unreadable file, wrong document type, missing value). A person can confirm or correct the result in the web app.

The hackathon brief is the source of truth for scope. Only document-comparison emails go through steps 2 to 4. Other categories are only classified.

## 2. Where things stand

| Area | Status |
|---|---|
| Classification (categories, intents, titles) | Done |
| Extraction (txt, pdf, docx, xlsx, scanned PDFs via vision fallback) | Done |
| Comparison | Done, with a fix for the `/INTERMEDIATE CONSIGNEE:` label (see section 8) |
| Human review (web form, saved decisions) | Done for confirm/correct, with a reason for each decision (section 9b) |
| Learning from review | Done for one case: blank SI values that reviewers repeatedly accept (section 9b) |
| Backend API (FastAPI) | Done, deployed |
| Database (Postgres) | Done, deployed |
| Web frontend (Next.js) | Done, deployed |
| Emails processed | 520 of 520 |
| Results | 454 OK, 47 MISMATCH, 19 NEEDS_REVIEW |
| Scored against the hackathon server | Yes — final score 0.930 (see `docs/SELF_EVAL_LOG.md`) |
| README written for judges | Not yet |

## 3. How the pieces fit together

```
Browser  ->  Vercel (web/)  ->  Render (api/ + src/)  ->  Neon Postgres
 people       the website        the backend logic         the stored data
                                       |
                                       +-> Gemini API (only when processing new emails)
```

| Service | Role | What breaks if it is down |
|---|---|---|
| **Vercel** | Hosts the Next.js website from `web/`. Rebuilds automatically on every push to `main`. | Nobody can open the site. |
| **Render** | Runs the FastAPI backend (`api/`, using `src/`). Holds the `GEMINI_API_KEY`. The free tier sleeps when idle, so the first request can take up to a minute. | The site stays up and shows a "backend unreachable, retrying" banner. |
| **Neon** | Hosted Postgres. Stores results, extracted SI/BL details and human review decisions. | The backend cannot read or save data. |

Live URLs: backend `https://shipping-checker-api.onrender.com` (`/health`, `/docs`). Frontend URL: see the Vercel project's production domain.

## 4. Project structure

```
averis_monash_larpmaxxing/
├── api/          Backend web service (FastAPI + database)
├── src/          The pipeline: read, classify, extract, compare, escalate
├── web/          Frontend website (Next.js)
├── prompts/      The instructions sent to Gemini
├── data/         The hackathon dataset (emails and attachments)
├── output/       Pipeline results and the local database
├── tests/        Automated tests
├── docs/         Documentation (this file)
├── main.py       Command-line entry point for the pipeline
├── loader.py     Hackathon-provided data loader
├── requirements.txt   Python packages
└── .env.example  Template for the settings file (.env)
```

### `src/`: the pipeline (the core logic)

| File | What it does |
|---|---|
| `pipeline.py` | Runs the stages in order for each email and returns the result. Reads up to two attachments (SI first, then BL). A missing file goes to review instead of crashing. |
| `classifier.py` | Asks Gemini to pick a category, an intent and a plain-English title. Validates that the intent belongs to the category. |
| `readers.py` | Turns attachments into text: `.txt`, `.pdf`, `.docx`, `.xlsx`. Scanned PDFs go to a Gemini vision fallback. Raises `UnreadableAttachment` when nothing usable can be read. |
| `extractor.py` | Pulls the seven fields from the text. Tries label matching first, uses Gemini when needed, and records a confidence per field. |
| `labels.py` | Label patterns that map different wording to one field (for example "Load Port" and "Port of Loading"). |
| `normalize.py` | Cosmetic clean-up of extracted values (company names, weights, placeholders like TBA or `???`). |
| `comparator.py` | Deterministic comparison, no AI. Ignores case, punctuation, bracketed port codes and the `/INTERMEDIATE CONSIGNEE:` label. Compares numbers as numbers. |
| `escalation.py` | Decides whether a case needs a human, and why. Reasons: `missing_attachment`, `wrong_doc_type`, `unreadable`, `missing_value`. |
| `report.py` | Builds each email's result entry. |
| `llm.py` | Gemini wrapper: caching, retries, rate limiting (`MAX_RPM`). |
| `cache.py` | Saves every Gemini response to `.cache/llm/`, so re-runs are free. Also enforces the `--max-calls` limit. |

### `api/`: the backend

| File | What it does |
|---|---|
| `main.py` | The web service. Endpoints listed in section 6. |
| `db.py` | Database layer. SQLite locally, Postgres when `DATABASE_URL` is set. Two tables (section 5). |
| `seed.py` | Loads `output/submission.json` into the database, and can store SI/BL details from the local cache. |

### `web/`: the frontend

| File | What it does |
|---|---|
| `app/page.tsx` | The whole page: summary tiles, filters, inbox and spam tables (each scrolls inside its own box), the detail panel with the SI/BL comparison, and the review form. |
| `lib/api.ts` | Types and functions that call the backend. The address comes from `NEXT_PUBLIC_API_URL`. |
| `app/globals.css` | Styling, with light and dark themes. |

### Other folders

- `prompts/`: `classify_prompt.txt` (categories, intents, title rules) and `extract_prompt.txt` (field extraction). Editing these changes model behaviour, and cached answers are keyed on the prompt, so changed prompts trigger fresh Gemini calls.
- `data/`: `inbox/` has 520 email JSON files, `attachments/` has the SI and BL files. Only the provided data, no answer key.
- `output/`: `submission.json` (results in the hackathon submission shape, plus `intent` and `title`) and `app.db` (local SQLite database). Both are git-ignored except the folder marker.
- `tests/`: `test_pipeline.py` and `test_extraction.py`. Run with `pytest`.

## 5. Data model

**Categories and intents** (defined in `src/classifier.py`)

| Category | Intents |
|---|---|
| BL_COMPARISON | `check_docs` |
| SI_REQUEST | `si_submission` |
| INVOICE_QUERY | `missing_gr`, `charges_breakdown`, `detention_demurrage`, `cancel_invoice`, `other_invoice` |
| GENERAL | `chase_document`, `automated_notice`, `schedule_update`, `other_general` |
| SPAM | `spam` |

The five categories match the hackathon scoring format, so do not rename them. Intents are our addition for readability. `chase_document` is an email asking us to send a draft BL, which is different from a request to check one.

**Statuses:** `OK` (no mismatch detected), `MISMATCH` (`defect_fields` lists the fields), `NEEDS_REVIEW` (`review_reason` says why).

**Database tables**
- `results`: one row per email. `entry` holds the category, intent, title, status, review reason and mismatched fields. `detail` holds the extracted SI/BL fields and readable text, so the site does not need Gemini to show them.
- `decisions`: human confirm/correct decisions, kept separate so a person's decision never gets overwritten by a re-run. The API applies them on top of the automatic result.

## 6. Backend API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Is the service up, and how many emails are stored |
| `GET /emails` | List emails; filters: `category`, `intent`, `status`, `q` |
| `GET /emails/{id}` | One email with its extracted fields and source text |
| `POST /emails/{id}/review` | Save a human decision (`OK` or `MISMATCH`, fields, note, reason, accepted blanks) |
| `GET /rules` | What reviewers have taught the system (votes per field, rules in force) |
| `POST /rules/apply` | Reprocess emails waiting on a missing-value review so learned rules take effect |
| `POST /runs` | Process emails in the background (only new ones by default) |
| `GET /runs/current` | Progress and failures of the current run |
| `POST /emails/{id}/retry` | Reprocess one email |

Try them at `/docs` on the backend address.

## 7. How to run things

**One-time setup:** `pip install -r requirements.txt`, then `cd web` and `npm install`. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`.

**Run the whole system locally (two terminals, both opened in the project folder):**
```
python -m uvicorn api.main:app --reload      # backend on :8000
cd web && npm run dev                        # frontend on :3000
```

**Process emails:** `python main.py --workers 4`. Add `--limit 20 --max-calls 40` for a small, capped test run.

**Load results into a database:** `python -m api.seed --details --max-calls 0`. Set `DATABASE_URL` first to load Neon instead of the local file.

**Tests:** `pytest`.

**Settings (`.env`, never commit it):** `GEMINI_API_KEY`, `CLASSIFY_MODEL`, `EXTRACT_MODEL`, `MAX_RPM` (Gemini requests per minute), `MAX_WORKERS`, `INBOX_SOURCE`, `DATABASE_URL` (Postgres, optional locally).

**Deploying:** push to `main`. Vercel rebuilds the site. Render redeploys the backend if its branch is set to `main` (Settings, Build & Deploy). Render environment variables: `DATABASE_URL`, `GEMINI_API_KEY`, `PYTHON_VERSION`. Vercel environment variable: `NEXT_PUBLIC_API_URL` (the Render address, no trailing slash).

## 8. Decisions worth knowing

- **Deterministic comparison.** Gemini reads the documents but never decides whether values match. Plain code does, so results are repeatable and explainable.
- **Escalate instead of guess.** Missing attachments, unreadable files, wrong document types and blank required fields all become `NEEDS_REVIEW` with a reason.
- **`/INTERMEDIATE CONSIGNEE:` label.** Some SIs write the notify party as `/INTERMEDIATE CONSIGNEE: ACME` while the BL says `ACME`. This was causing 31 false mismatches across 22 emails, and the comparator now ignores the label. Mismatch count dropped from 69 to 47.
- **Postgres over files.** Render's disk resets on restart, so results and human decisions live in Neon.
- **Postgres driver.** We use `pg8000` (pure Python) because some Windows machines block the compiled `psycopg` library.
- **`has_defect`** is true only for `MISMATCH`, not for `NEEDS_REVIEW`.
- **Party fields** are compared on company name only, not addresses.

## 9. Known gaps and next steps

- The 6 unprocessed emails (email_515 to email_520) need Gemini quota. Then run `python main.py --workers 4` and `python -m api.seed --details`.
- Low-confidence extractions are not yet routed to human review. Failed emails are skipped rather than shown as failures in the report.
- The remaining 47 mismatches were only partly spot-checked. The ones reviewed looked like genuine differences (ports, container counts, weights), but not all were checked.
- `README.md` describes the pipeline but not the API, database or web app. It should be updated before submission, with the live link and design notes.
- `__pycache__` folders are tracked in git and show up as modified after every run. Untrack them.

## 9b. Learning from human review

When the system asks for a review, the reviewer picks a reason. One reason teaches the system: **"Blank on the SI is fine - the BL has it"**, with the blank fields ticked.

- A field becomes a **learned rule** after 2 decisions accept it (`MIN_VOTES` in `src/learning.py`). Rules are worked out from the `decisions` table, so they survive restarts and are undone if decisions change.
- A rule only excuses a field that is **blank on the SI and filled in on the BL**. A blank BL, or a blank on both sides, always goes to a person. Missing attachments, unreadable files and wrong document types never learn anything.
- A vote is only accepted for fields that really are blank on that email (checked against its stored details).
- When a rule is learned, the emails still waiting on a `missing_value` review are reprocessed in the background, keeping their stored category, intent and title (no new classification call). Emails resolved this way show a **learned rule** tag.
- **Learned rules and human decisions only exist in the API and website.** `main.py` and `output/submission.json` do not apply them, so the scored output is unchanged.
- The API has no login, so anyone who can reach it can post decisions. Add authentication before relying on learned rules for anything important.

## 10. Working rules

- Never commit `.env`, API keys or the Neon connection string. If one leaks, rotate it.
- Work on `main`, and pull before you start (`git pull`).
- The pipeline and comparator have tests. Run `pytest` after changing anything in `src/`.
- Changing a prompt makes every cached answer stale and costs Gemini calls, so check the free-tier limit before a full re-run.
