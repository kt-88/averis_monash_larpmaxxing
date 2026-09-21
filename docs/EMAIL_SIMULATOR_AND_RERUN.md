# Email simulator and "re-run with Gemini"

Two features for demos, testing and trust. Both use the real pipeline (`src/`), so what you see is what the
system really does.

## 1. Email simulator (the Compose button, or press `c`)

Write an email, attach an SI and a draft BL (paste text or upload `.txt`, `.pdf`, `.docx`, `.xlsx`), and send it.
The backend stores it, runs it through classify, extract, compare and escalate, and the result appears in the inbox.

- Eight ready-made examples: documents match, different label wording, mismatch, blank value, BL missing,
  wrong document attached, invoice question, spam. Each says what result to expect.
- Composed emails get **Gemini's second opinion automatically**, the same check that "Re-run with Gemini" does:
  besides classifying the email, Gemini reads the SI and the BL on its own, and the page shows how many of the 14
  values it matched. A comparison email therefore takes about 10 to 20 seconds and 3 Gemini calls (a plain email,
  1 call). If the second opinion cannot be had, the email is still processed normally.
- The inbox and the details show **the subject you typed**. Gemini's own plain-English title is still shown, labelled as
  Gemini's (the provided emails keep showing their titles as before).
- Simulated emails are tagged **Simulated**, have ids like `sim_0001`, and are kept out of the summary numbers,
  the review queue and the CSV report. They never enter `output/submission.json` (`python main.py` only reads the
  provided inbox).
- They live in the database (`sim_emails`, `sim_files`, created on first use), so they survive restarts on Render.
  `loader.py` is untouched: `api/livebox.py` wraps it and adds the simulated emails.

| Endpoint | What it does |
|---|---|
| `GET /simulate/info` | Is the simulator on, and its limits |
| `POST /simulate/emails` | Store the email (JSON, attachments as base64) and process it in the background |
| `GET /simulate/emails/{id}` | `processing`, `done` (with the result and `second_opinion`) or `failed` (with a plain reason) |
| `DELETE /simulate/emails/{id}` | Remove it, its result and any decision about it. Provided emails can never be deleted |

If processing fails (for example Gemini's daily quota), nothing is left behind and the draft stays in the window.

## 2. Re-run with Gemini (Details tab of any email)

The older **Retry processing** button re-uses Gemini's *saved* answers, so it can only repeat itself. **Re-run with
Gemini** ignores the saved answers and asks again:

1. Gemini classifies the email afresh.
2. For a comparison, Gemini also reads the SI and the BL on its own, as a second opinion on the 7 fields.
3. The page shows what changed, and any value Gemini read differently (rules read / Gemini read).

The values taken from the document itself always win, and a person's decision is never touched. If Gemini
cannot be reached, the stored result is left exactly as it was.

`POST /emails/{id}/rerun` returns `{changed, changes, field_changes, agreement: {checked, agree, disagreements}, gemini_calls}`.
It costs about 3 Gemini calls (5 for scanned PDFs) and takes 10 to 25 seconds.

How it works inside: `src/cache.py` has `fresh_llm_calls()` (do not read saved answers, but save the new ones), and
`src/extractor.py` has `cross_check_with_llm()` (always ask the LLM too). Each field now also carries `llm` (what
Gemini read) and `agree` (whether it matched), both `null` when Gemini was not asked.

## Settings (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `SIMULATOR_ENABLED` | `1` | `0` switches the simulator off (the Compose button disappears) |
| `SIM_MAX_PER_HOUR` | `30` | Simulated emails per hour, to protect the Gemini quota |
| `SIM_MAX_STORED` | `200` | Simulated emails kept at once |
| `RERUN_MAX_PER_HOUR` | `60` | Re-runs per hour. The same email can be re-run once every 10 seconds |

## Things to know

- These endpoints have no login, like the rest of the API. Anyone with the backend URL could use Gemini through
  them (limited by the caps above). For a public deployment, set `SIMULATOR_ENABLED=0` or add an API key.
- The free Gemini tier allows 500 requests a day per model, shared with everything else.
- Tests: `tests/test_simulator.py` (30 tests, no Gemini key needed) and additions in `tests/test_extraction.py`.
- Files added: `api/sim_store.py`, `api/livebox.py`, `api/simulator.py`, `api/rerun.py`, and in `web/`:
  `components/Compose.tsx`, `components/Rerun.tsx`, `lib/tools.ts`, `lib/samples.ts`.
  Small edits: `api/main.py` (3 places), `src/cache.py`, `src/extractor.py`, and the page, detail panel,
  email table, summary and styles in `web/`.
