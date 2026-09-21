# Submission checklist

Deadline: **22 Sep, 12:00**. Work top to bottom. Each item says who owns it.

This covers the repo and the three hosted services. It does **not** cover the organizer's own
submission form (what to upload, where) — check that separately against their instructions.

---

## Part A — Score issues from `docs/SELF_EVAL_LOG.md`

The last scoring run gave **0.930**. Four issues were found. Status:

| # | What | Emails | Status |
|---|---|---|---|
| A1 | Classifier calls "please send the draft BL" `GENERAL`; reference wants `BL_COMPARISON` | 91 | **Open** — classification owner. Biggest lever: stage 1 is 30% of the score. None of the 91 hides a real defect. |
| A2 | PDF reader shuffled overlapping label and value ("ConsCigEnReIEeX") | 208, 351, 407 | **Fixed** in `src/readers.py` |
| A3 | Scanned PDFs were trusted after OCR; reference wants them escalated | 512, 513, 514 | **Fixed** — now `NEEDS_REVIEW / unreadable` |
| A4 | A PDF with a broken index was rejected; reference expects it read | 499 | **Fixed** — now read and compared |

**What the reader fixes changed** (verified by diffing all 250 attachments before and after: 12 changed, 238 did not):
- **A2:** text is read in the order the PDF draws it, so a long label and its value no longer interleave.
- **A3:** an image-only scan is still transcribed by the vision model, but only so the reviewer has something
  to read (labelled *"Transcribed from a scanned image by Gemini. Check it against the original."*).
  The email is always escalated, and a failed or unavailable transcript cannot stop that.
- **A4:** if `pdfplumber` cannot open a PDF, it is retried with PDFium (the engine inside Chrome), which repairs a
  broken index. Files that are genuinely corrupt (511, 515) still fail and are reported unreadable.

**Effect on `output/submission.json`:** exactly 7 emails changed, and they are the 7 in the log.

| Email | Before | After |
|---|---|---|
| 208, 407 | `MISMATCH` on notify_party | `OK` |
| 351 | `MISMATCH` on notify_party, container_count, gross_weight_kg | `MISMATCH` on container_count, gross_weight_kg |
| 499 | `NEEDS_REVIEW / unreadable` | `MISMATCH` on gross_weight_kg (SI 40,326 kg vs BL 41,326 kg) |
| 512, 513, 514 | `OK` | `NEEDS_REVIEW / unreadable` |

Total: 453 OK, 46 MISMATCH, 21 NEEDS_REVIEW (was 454 / 47 / 19).

**The 0.930 score is now stale. Re-score** (see C3). The expected direction is up, but it has not been measured.

---

## Part B — Package the repo

### B1–B3. Done

- **Compiled files untracked.** 9 `.pyc` files were committed; they are no longer tracked. If a teammate's
  `git pull` says *"local changes would be overwritten"* for a `.pyc`, they should discard their local copy of
  that file (it is regenerated automatically) and pull again.
- **Unused files removed:** `app/viewer.py` (old Streamlit page), 5 leftover Next.js template images, and
  `streamlit` and `pandas` from `requirements.txt` (only the viewer used them). `pypdfium2` is now listed explicitly
  because the reader imports it directly (it was already installed as part of `pdfplumber`).
- **`.env.example` completed.** It listed 7 variables; the code reads 16. All are now documented.
- `web/README.md` was the untouched create-next-app text; it now describes this app.

**Kept on purpose** (they look deletable but are not): `web/app/favicon.ico` (Next.js finds it by filename),
`web/AGENTS.md` and `web/CLAUDE.md` (`next dev` recreates them), and `loader.py` (provided by the organizers).

### B4. Check nothing private is in the repo (2 min)

```
git log --all --oneline -- .env          # must print nothing
git grep -l "AIza" $(git rev-list --all) # must print nothing (Gemini keys)
```

The Neon connection string must appear **only** in the Render dashboard, never in a file. If either check finds
something, rotate that key immediately — a leaked key stays live until it is revoked, whatever Git says.

### B5. What ships

| Include | Note |
|---|---|
| `output/submission.json` | The graded deliverable. 520 entries, verified complete. |
| `src/`, `api/`, `web/`, `prompts/`, `tests/` | The system. |
| `README.md`, `docs/` | How it works and how to run it. |
| `requirements.txt`, `web/package.json` | Dependencies. |
| `data/` | Provided dataset — leave exactly as given. |

Never commit: `.env`, `.cache/`, `output/app.db`, `scratch/`. All are in `.gitignore`.

---

## Part C — Verify before submitting

Run these in order. Every one must pass.

### C1. The repo runs from scratch

Pretend you are a judge who just cloned it:

```
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python -m pytest tests -q
```

Expected: build succeeds, **131 tests pass**.

### C2. The submission file is complete

```
python -c "import json; from loader import Inbox; s=json.load(open('output/submission.json',encoding='utf-8')); ids=[e['email_id'] for e in Inbox('data')]; print('entries', len(s), '| missing', [i for i in ids if i not in s], '| stray', [k for k in s if k not in ids])"
```

Expected: `entries 520 | missing [] | stray []`. The `stray` check matters: emails written in the simulator
(`sim_0001`, …) must never appear.

### C3. Re-score

`output/submission.json` changed (Part A), so the old score no longer applies. Run the organizer's scoring server
(`docker compose up --build`), record the new score in `docs/SELF_EVAL_LOG.md`, and compare to 0.930.

If anyone changes `src/` or `prompts/` after this, re-run the pipeline (`python main.py --workers 8`) and re-score.
The pipeline is rate-limited (`MAX_RPM`, default 12) and the free Gemini tier allows **500 requests per day**,
resetting at 07:00 UTC (≈5pm Melbourne). Cached answers are reused, so only changed prompts cost calls.
**Do not delete `.cache/llm/`** — it holds every answer already paid for.

### C4. The three hosted services

Settings live in the provider dashboards, not in the repo, so someone has to open each one.

**Neon (database).** The site shows what is in Neon, not `output/submission.json`, so Neon must be refreshed.
With `DATABASE_URL` set to the Neon string, run both, in this order (free, from the local cache, no Gemini calls):

```
python -m api.seed --details --max-calls 0
python -c "from api.main import process_and_save; process_and_save(['email_208','email_351','email_407','email_499','email_512','email_513','email_514'])"
```

The first loads the 520 results. The second recomputes the 7 changed emails' stored details; without it the site
would show new results next to old field data for those emails. Check: open `email_208` (notify party `CERIEX` on
both sides, status OK) and `email_512` (needs review, with the labelled transcript in its source documents).

**Render (backend).**
- Environment variables set: `GEMINI_API_KEY`, `DATABASE_URL`, `CORS_ORIGINS`.
- Open `<render-url>/health` → `{"ok": true, "emails_processed": 520}`.
- Open `<render-url>/docs` → the API page loads.
- **The free tier sleeps when idle.** The first request after a quiet period takes up to a minute. Wake it a few
  minutes before any demo or judging.
- Render installs from `requirements.txt`; the `pypdfium2` line is new, so a redeploy is needed.

**Vercel (frontend).**
- `NEXT_PUBLIC_API_URL` is set to the Render URL, with no trailing slash.
- The latest commit actually deployed — check the Deployments tab. On the free plan a deployment can be
  **blocked when the commit author is not the account owner**, so a teammate's push may silently not deploy.
- Open the site and confirm: the counters load, clicking an email shows its fields, and the **Compose** button
  appears (it only appears when the backend answers).

### C5. One real end-to-end pass (5 min, do this last)

On the **live** site, not locally:

1. Open an email with a mismatch → the differing fields are highlighted.
2. Click a grey source line → it highlights inside the source document.
3. Press `c`, pick the "Documents match" example, send it → it processes and lands in the inbox tagged
   **Simulated**. (Uses ~3 Gemini calls.)
4. Delete that test email afterwards, so the demo inbox is clean.
5. Confirm the counters still read 520 emails / 130 comparisons — simulated emails must not be counted.

### C6. Freeze

Agree a time to stop changing code — **6pm on 21 Sep** is sensible. After that: no edits, only rehearsing the demo.
A stable, scored submission beats an untested improvement.

---

## Quick division of work

| Person | Owns |
|---|---|
| Classification | A1, then re-run C3 |
| Comparison / reporting | C2, C3, keep `SELF_EVAL_LOG.md` current |
| Whoever holds the accounts | C4 (Neon, Render, Vercel), C5 |
| Anyone | B4, C1 |
