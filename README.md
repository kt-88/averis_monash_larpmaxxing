# Shipping document verification

Reads a shipping team's inbox, finds the emails asking for a document check, and compares the Shipping Instruction (SI) against the draft Bill of Lading (BL) before the draft is finalised.

- **Live app:** [add the Vercel URL]
- **API:** [add the Render URL] (`/health`, `/docs`)

The first load can take up to a minute while the free-tier backend wakes up.

## Overview

Every email is classified into one of five categories (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`), given a finer *intent* and a plain-English title. Document-check emails go on to be compared on seven fields: shipper, consignee, notify party, port of loading, port of discharge, container count and gross weight (kg).

Each email ends in one of three states:

| Status | Meaning |
|---|---|
| `OK` | No mismatch detected |
| `MISMATCH` | `defect_fields` names the fields that differ, SI and BL shown side by side |
| `NEEDS_REVIEW` | The system would not decide alone; `review_reason` says why |

The AI reads documents; plain code decides whether values match. Anything the code cannot decide confidently goes to a person with the reason and the source evidence, and their decision updates the report.

Current run over the provided dataset: 520 emails, **453 OK, 46 MISMATCH, 21 NEEDS_REVIEW** (`output/submission.json`).

## Running it locally (Python)

Nothing is hosted in these steps: no Vercel, no Render, no Postgres. A local SQLite file is used automatically when `DATABASE_URL` is unset.

**Setup**

```
pip install -r requirements.txt
copy .env.example .env          # then set GEMINI_API_KEY
```

Emails are read from `data/` (`inbox/*.json` and `attachments/`) through the provided `loader.py`.

**Option A — the pipeline only (no web app)**

```
python main.py --limit 20 --max-calls 40      # small capped run
python main.py --workers 8                    # full run -> output/submission.json
pytest                                        # 131 tests
```

`main.py` flags: `--source` (data folder or an HTTP inbox), `--limit`, `--workers`, `--max-calls` (hard cap on real Gemini calls), `--out`, `--submit` (post to the organizer's scoring server when `--source` is that server).

**Option B — the web API as well**

```
python -m api.seed --details --max-calls 0    # load results into the local database
python -m uvicorn api.main:app --reload       # http://localhost:8000/docs
```

`/docs` is a working UI in itself: every endpoint can be called from the browser, so the Python side is usable without Node.

**Option C — the full app locally.** The interface is a Next.js app, so this step needs Node. With the backend from Option B running:

```
cd web
npm install
npm run dev                                   # http://localhost:3000
```

The frontend calls `http://localhost:8000` unless `NEXT_PUBLIC_API_URL` says otherwise.

**Settings** (`.env`, never committed): `GEMINI_API_KEY`, `CLASSIFY_MODEL`, `EXTRACT_MODEL`, `VISION_MODEL`, `MAX_RPM` (Gemini requests per minute, default 12), `MAX_WORKERS`, `INBOX_SOURCE`, `DATABASE_URL`, `CORS_ORIGINS`, and the simulator caps. See `.env.example`.

## Technical architecture

```
Browser ──> Next.js (Vercel) ──> FastAPI (Render) ──> Postgres (Neon)
                                      │
                                      └──> Gemini API
```

Three deployable parts over one shared pipeline:

| Layer | Path | What it is |
|---|---|---|
| Pipeline | `src/` | Pure Python. Read, classify, extract, compare, escalate. No web or database knowledge, so it runs from the CLI and from the API unchanged. |
| Backend | `api/` | FastAPI wrapper: HTTP endpoints, storage, background runs, the email simulator. |
| Frontend | `web/` | Next.js app. Client-side only, talks to the backend over HTTP. |

**Why split this way.** The frontend is hosted apart from the backend, so a backend restart or cold start leaves the page up (it shows a "waking the server" banner and reconnects itself). State lives in Postgres because Render's disk resets on restart and a reviewer's decision has to survive it. The Gemini key and database URL are environment variables on the backend, never in the repo and never in the browser.

**Storage** (`api/db.py`) — SQLite locally, Postgres when `DATABASE_URL` is set, via SQLAlchemy and the pure-Python `pg8000` driver (no compiled `libpq`, which some managed Windows machines block).

| Table | Holds |
|---|---|
| `results` | One row per email: the result entry, plus the extracted SI/BL fields and readable text, so the site never needs Gemini to display an email |
| `decisions` | Human confirm/correct decisions, kept separate so a re-run never overwrites a person's judgement |
| `sim_emails`, `sim_files` | Emails composed in the simulator and their attachments |

**API**

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, and how many emails are stored |
| `GET /emails` | List with `category`, `intent`, `status`, `q` filters |
| `GET /emails/{id}` | One email with its fields, source text and evidence |
| `POST /emails/{id}/review` | Save a human decision (status, fields, reason, note) |
| `POST /emails/{id}/retry` | Reprocess using the cached Gemini answers |
| `POST /emails/{id}/rerun` | Re-ask Gemini and report what changed and where it disagrees |
| `POST /runs`, `GET /runs/current` | Background processing and its progress, including failures |
| `GET /rules`, `POST /rules/apply` | Rules learned from review, and re-checking against them |
| `/simulate/*` | Compose, poll and delete a test email |

## Implementation details

**Pipeline stages** (`src/`)

| Stage | File | Notes |
|---|---|---|
| Read | `readers.py` | txt/pdf/docx/xlsx to text, tables included. A PDF pdfminer refuses is retried with PDFium, which repairs a broken cross-reference index; 0-byte, truncated, corrupt or garbled files raise `UnreadableAttachment`. An image-only scan is never trusted for an automatic decision: it is transcribed by a vision model for the reviewer and raised as `ScannedDocument`, so the email is always escalated. |
| Classify | `classifier.py` | Gemini. The newest message is split from the quoted thread, so a stale subject or an old reply cannot decide the category. Returns category, intent and title, and an intent that does not belong to its category is rejected. |
| Extract | `extractor.py`, `labels.py` | Label patterns first (`labels.py` maps "Load Port" and "Port of Loading" to one field), Gemini for what is left. Each field is stored with its value, the source line it came from and a confidence. Absent label to `null`; present but blank (`???`, `____`, `TBA`, `N/A`) to `"BLANK"`. |
| Normalise | `normalize.py` | Cosmetic only: company suffixes, address lines, trailing phone numbers, weight units and thousands separators. |
| Compare | `comparator.py` | No AI. Case and punctuation insensitive names, bracketed port codes ignored, a leading `/INTERMEDIATE CONSIGNEE:` label stripped, numbers compared as numbers. |
| Escalate | `escalation.py` | Precedence: `missing_attachment` > `unreadable` > `wrong_doc_type` > `missing_value`. Wrong-document detection reads the document title deterministically and skips extraction, saving calls. |
| Report | `report.py` | Builds the submission entry per email. |

**Gemini use** (`llm.py`, `cache.py`). Every response is cached on disk under `.cache/llm/`, keyed by a hash of model and prompt, so re-runs cost nothing and a changed prompt invalidates only itself. Requests are spaced across threads to stay under `MAX_RPM`, and `--max-calls` raises `BudgetExceeded` rather than exceeding the free daily quota. A run prints `[llm] API calls made: N` on each real call.

**Human review and learning** (`learning.py`). A reviewer records a reason with each decision. One reason teaches the system: *"blank on the SI is fine, the BL has it"*. After `MIN_VOTES` (2) agreeing decisions, that field becomes a learned rule, and emails still waiting on a `missing_value` review are reprocessed in the background, keeping their stored category and title. A rule only ever excuses a field blank on the SI and present on the BL. Missing attachments, unreadable files and wrong document types never learn anything. Rules are derived from the `decisions` table, so they survive restarts and reverse if decisions change. Learned rules and human decisions exist only in the API and site — `main.py` and `output/submission.json` are unaffected, so the scored output stays reproducible.

**Email simulator** (`api/simulator.py`, `api/sim_store.py`, `api/livebox.py`). Compose an email, attach an SI and BL, and it runs through the same pipeline and appears in the inbox tagged `sim_`. `LiveInbox` wraps the organizer's `loader.py` rather than modifying it. Simulated emails are excluded from the summary figures, the review queue and the CSV report, and never enter `output/submission.json`. Composed emails also get Gemini's independent second opinion on the 14 values.

**Frontend** (`web/`). One client-rendered page (`app/page.tsx`) with components for the list, detail panel, review form, run control, summary and compose window. Filters and the open email are kept in the address bar, so any view can be bookmarked or shared. `lib/report.ts` exports the report as CSV.

**Decisions and assumptions**
- `has_defect` is true only for `MISMATCH`. A blank or unreadable value is not a defect, so `NEEDS_REVIEW` entries get false.
- A `BL_COMPARISON` email with no attachments is `NEEDS_REVIEW / missing_attachment`, not a guess.
- Party fields are compared on company name only, not on addresses.
- An email that only asks us to *send* a draft BL, with nothing attached, is `GENERAL / chase_document`: there is nothing to compare yet.

**Tests.** 131 tests (`pytest`) cover the readers, extractor, comparator, escalation precedence, learning and the review API. The API tests run against a temporary SQLite file with the pipeline stubbed, so no Gemini calls are made.

## Challenges faced

- **Full-stack was new to us.** Our background is cybersecurity coursework, mostly theoretical, and none of us had deployed a full-stack app before. We learned FastAPI, Next.js, Postgres, Render and Vercel while building, leaning on documentation and AI coding tools, and used the test suite and the organizer's scorer to check the result independently.
- **A bug that looked like the wrong bug.** A notify party read as `Notify Party/Intermediate ConsCigEnReIEeX`: the label and value are overlapping text objects in the PDF, and sorting characters by position interleaved them. It presented as a comparison error but was an extraction error, found by tracing values back to the source document.
- **Telling a discrepancy from a formatting difference.** Our first full run flagged 69 mismatches; 22 were false alarms from one label prefix. Fixing that needed a normalisation layer we could explain, not a looser comparison.
- **Damaged and scanned PDFs.** Some files would not open at all, others had no text layer. The answer was a repair path, a vision fallback, and a rule that a scan always goes to a person, however clean the transcription looks.
- **Free-tier limits shaped the design.** About 500 Gemini requests a day forced caching, rate limiting and call caps before they were convenient.
- **Environment problems we did not expect.** An Application Control policy on a Windows machine blocked the compiled Postgres driver, so we moved to pure-Python `pg8000`. Render's free tier sleeps, so the UI had to handle a cold start. Vercel refused to build a teammate's commits on a private repo.

## Future roadmap

Near term:
1. **Ingest real mail** over IMAP or the Microsoft Graph or Gmail APIs, with attachments in object storage instead of the server's disk.
2. **A job queue with workers** so processing leaves the web request, bursts do not slow the site, and failures retry visibly.
3. **Authentication and roles** (reviewer, admin), CORS restricted to the real site, API rate limits and an audit log of who decided what — human decisions change results, so they need accountability.

Later:
4. **Model routing by difficulty:** a cheap model for classification, a stronger or vision model only for hard or scanned documents, on a paid tier or in batch mode.
5. **Wider learning with an approval step,** plus a regression set built from confirmed cases so a prompt or model change can be verified before release.
6. **More document types** (commercial invoice, packing list), per-customer field mappings and multi-tenant separation.
7. **Operational monitoring:** error rates, queue depth, Gemini spend and the reviewer-agreement rate, with alerts.

None of the above is built yet, and the system has not been load-tested beyond the provided dataset.


# Written responses

## Problem-solution alignment

**The problem.** A shipping team's inbox mixes document-check requests, new shipping-instruction requests, invoice questions, general updates and spam. Someone has to read each message, find the requests that need action, and compare a Shipping Instruction (SI) against a draft Bill of Lading (BL) field by field. That is repetitive, and a missed difference (a wrong port, a container count off by one, a weight that differs by 1,000 kg) causes corrections and delays after the BL is finalised.

**How each part of the brief is answered**

| The brief asks for | What we built |
|---|---|
| **Classify** each email | Gemini sorts every email into the five required categories. We added a finer *intent* (for example `missing_gr`, `chase_document`) and a plain-English title, so the inbox reads clearly at a glance. |
| **Extract** the shipment fields | The reader turns `.txt`, `.pdf`, `.docx` and `.xlsx` attachments into text, including tables. The extractor reads the 7 fields and maps different labels to one field ("Load Port" and "Port of Loading"). |
| **Compare** and show SI vs BL | A plain Python comparator, not the AI, decides whether values match. It ignores harmless formatting (case, punctuation, bracketed port codes, address lines, a `/INTERMEDIATE CONSIGNEE:` label) and compares numbers as numbers. Mismatches are shown side by side. If nothing differs, the site says "No mismatch detected". |
| **Ask for help** when unsure | Missing attachments, unreadable files, wrong document types, blank required values and scanned images all go to a person as `NEEDS_REVIEW`, with the reason and the source text. The reviewer confirms or corrects, and the site uses their decision. |

**Design choices that follow from the problem**
- *The AI reads; code decides.* Gemini extracts values, but whether two values match is deterministic code. The same input always gives the same answer, and every mismatch can be explained.
- *Escalate rather than guess.* A confident wrong answer on a shipping document is worse than a question to a person. Scanned images are always escalated, even when the AI's transcription looks clean.
- *Avoid false alarms.* Our first full run flagged 69 emails as mismatches. Checking them against the source files showed that 22 were false alarms caused by a label some SIs put in front of the notify party. Fixing the comparator brought the flagged count down without hiding any real difference.
- *Known trade-off.* Emails that only ask us to *send* a draft BL (nothing attached) we label `GENERAL / chase_document`, because there is nothing to compare. In our last self-evaluation the reference labelled many of these as document-comparison requests. No real mismatch was missed because of it (all of those emails are OK in the reference), but it lowered our classification score. [Update this sentence if the team changes the rule.]

---

## AI and cloud infrastructure integration

**AI (Google Gemini)**
- *Classification and titles:* a low-cost model (`gemini-3.5-flash-lite`) reads the newest message, ignores signatures and quoted threads, and returns a category, an intent and a title.
- *Extraction:* label patterns handle clean documents, and Gemini handles messy ones. Each field is stored with a confidence value.
- *Scanned documents:* image-only PDFs are sent to a vision model to produce a transcript. The transcript is only there so a reviewer has something to read, is clearly labelled as AI-transcribed, and the email is always escalated.
- *Second opinion:* "Re-run with Gemini" asks the model to read the SI and BL again independently and shows how many of the 14 values it agrees on. It is a check for the reviewer and does not silently overwrite the result.
- *Cost and rate control:* every model answer is cached on disk by a hash of the model and prompt, so re-runs are free. Requests are spaced to a configurable limit (`MAX_RPM`), and a call cap (`--max-calls`) protects the free daily quota.

**Cloud (three services, each with one job)**

```
Browser -> Vercel (Next.js website) -> Render (FastAPI backend) -> Neon (Postgres)
                                              |
                                              +-> Gemini API
```

- **Vercel** hosts the website and rebuilds it on every push to `main`.
- **Render** runs the backend, holds the Gemini key, and reads and writes the database.
- **Neon (Postgres)** stores results, extracted SI/BL details and human review decisions. We use a database because Render's disk resets on restart, and a person's decision has to survive it.
- *Resilience:* the website is on a different host from the backend. If the backend restarts or is waking up, the page stays up, shows a "waking the server" message, and reconnects on its own.
- *Secrets:* the Gemini key and the database address are environment variables on Render, never in the repository.

**Human-in-the-loop, built as a feedback loop.** Reviewers record a reason for each decision. When reviewers repeatedly accept the same case (a field left blank on the SI but filled in on the BL), the system learns a rule and re-checks the emails still waiting on it. These learned rules are limited, visible on the page, and never apply to missing, unreadable or wrong documents.

---

## User feedback and testing

**What we tested, and what it showed**
- *Automated tests:* 131 tests pass (`pytest`), covering the readers, extractor, comparator, escalation rules, learning and the API.
- *The organizer's self-evaluation server:* we submitted all 520 emails and read the disagreements one by one against the source documents instead of only looking at the score. That found real problems: an overlapping-text bug in PDF reading, three scanned files we were trusting too much, and a malformed PDF we rejected but the reference could read.
- *Reviewing our own mismatches:* checking flagged emails against the source files found the false-alarm pattern described above.
- *Email simulator:* the site has a "Compose" window with eight ready-made scenarios (documents match, different label wording, a real mismatch, a blank value, BL missing, wrong document attached, invoice question, spam), each stating the expected result. It lets anyone try the system on their own email and attachments without touching the provided data.
- *Cross-checking:* teammates audited each other's areas, and one of us re-diffed the whole submission against the reference to confirm nothing else was hiding.

**User feedback.** [Fill in honestly. We have not documented feedback from real shipping-operations staff. If any classmates, mentors or hackathon staff tried the site, add who they were, what they did, what they said and what we changed because of it. If none, say: "We have not yet tested with shipping-operations users. The simulator and review screen were built so we can."]

---

## Coding challenges

**Unfamiliarity with full-stack development.** Our course work at Taylor's University has been in cybersecurity and has been mostly theoretical. Before this hackathon we had not built, connected and deployed a full-stack application. Concepts we knew by name, such as APIs, databases, hosting and environment variables, we had never put together, and nobody on the team had used FastAPI, Next.js, Postgres, Render or Vercel. We learned by building: online documentation, tutorials and forum answers to understand each piece, and AI coding tools to explain errors, suggest structure and speed up writing code. We treated the AI's output as a draft to run, test and question. The pytest suite and the self-evaluation server gave us a way to check the results independently. We are open about this because it is the honest account of how the project was made, and the biggest thing we gained was practical experience of the whole path from a script to a live site.

**Specific problems we had to solve**
- *Overlapping text in PDFs.* One document's label and value overlapped, and the reader interleaved the characters (`Notify Party/Intermediate ConsCigEnReIEeX`). It looked like a comparison bug but was an extraction bug, which we found by tracing the values back to the source. The reader now uses the order the PDF draws the text.
- *Damaged and scanned PDFs.* Some files could not be opened, and some had no text at all. We added a repair path, a vision fallback, and a rule that scans always go to a person.
- *Two mismatches that were not mismatches.* Separating a real discrepancy from a formatting difference took reading many documents and building a normalisation layer we could explain.
- *Free-tier limits.* The free Gemini quota (about 500 requests a day) forced caching, rate limiting and call caps. We learned to check what a re-run would cost before starting one.
- *Deployment problems we had not expected.* Windows blocked compiled libraries on some machines, so we switched to a pure-Python Postgres driver. Render's free tier sleeps and delays the first request, so the site shows a clear waiting message. Vercel refused to deploy commits from a teammate who was not on the project, so we had to understand how deployment permissions work.
- *Working as a team in git.* Merge conflicts, branches and generated files being committed by mistake taught us why version control habits matter.

---

## Success metrics

**Measured**
- *Coverage:* all 520 emails are processed, with no crashes and no email left out.
- *Reference score:* our last self-evaluation was **0.930** overall (classification macro-F1 0.860, defect-detection F1 0.968, end-to-end 0.957). [Re-score after the latest changes and update these figures with the date.]
- *Accuracy of differences:* in the last audit, all 129 correctly-routed comparison pairs matched the reference on the field level except 7 emails, each of which we traced to a cause. No real mismatch was missed by mis-routing.
- *False alarms:* mismatches fell from 69 to 46 after we fixed the notify-party label handling, and the audit found no remaining false alarms from the comparator.
- *Reliability:* 21 emails are currently escalated with a stated reason (6 missing attachment, 5 unreadable, 5 wrong document type, 5 missing value) instead of being guessed. Current totals: 453 OK, 46 MISMATCH, 21 NEEDS_REVIEW.
- *Cost:* re-running the whole inbox costs no Gemini calls once answers are cached.

**Measures the site reports, with their limits**
- The summary shows a "time saved" estimate. It assumes 3 minutes per manual check, and the assumption can be changed on the page. It is an estimate, not a measurement.

**What we would track with real users** [adjust to what the team agrees]
- Time from an email arriving to a decision.
- The share of `NEEDS_REVIEW` cases a reviewer agrees needed a person (are we asking for help at the right times?).
- How often a reviewer overrules an automatic result (false alarms and misses).
- Gemini cost per email.

---

## Scalability plans

**Where we are today (free tiers, single instance).** The system handles the 520-email dataset comfortably. Its limits are known: the free Gemini quota, one backend instance that sleeps when idle, no login on the API, and an inbox read from JSON files.

**What we would do to scale it**
1. *Real inbox ingestion.* Replace the JSON files with a mailbox connection (IMAP or Microsoft Graph or Gmail API) that pulls new mail and stores attachments in object storage such as S3, not on the server's disk.
2. *A job queue and workers.* Move processing out of the web request into a queue (for example Celery or a cloud queue) with several workers, so a burst of email does not slow the site, and failed jobs retry visibly.
3. *Cost and quota.* Move to a paid Gemini tier or batch mode, keep the cache keyed by content, and route work by difficulty: a cheap model for classification, and a stronger or vision model only for hard or scanned documents.
4. *Database.* Neon already scales with connection pooling. We would add indexes on status and category, and archive old emails.
5. *Backend hosting.* Move from a sleeping free instance to an always-on, auto-scaling container service (Render paid tier or Cloud Run) behind a health check.
6. *Security and access.* Add login and roles (reviewer, admin), restrict CORS to the real site, rate-limit the API, and audit-log who made each review decision. This matters because human decisions change the results.
7. *Accuracy at scale.* Widen the learned-rule system with an approval step, track review outcomes over time, and build a regression test set from confirmed cases so prompt or model changes can be checked before release.
8. *More documents and customers.* Add document types beyond SI and BL (commercial invoice, packing list), per-customer field mappings, and multi-tenant separation of data.
9. *Monitoring.* Track error rates, queue length, Gemini spend and the review-agreement rate, with alerts.

**What we did not do.** None of the points above are built yet. We list them as our plan, and we have not load-tested the system beyond the provided dataset.
