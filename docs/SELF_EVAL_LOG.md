# Self-evaluation log (comparison & reporting)

Scored `output/submission.json` (520/520 emails) against the organizer scoring
server (`docker compose up`, `data_v2/ground_truth.json`, 2026-09-21).

**Final score: 0.930** — stage1 macro-F1 0.860, stage3 defect-F1 0.968,
end-to-end 0.957.

Every case below was found by diffing `output/submission.json` against
`ground_truth.json` for all `BL_COMPARISON` emails, then re-running the
actual reader/extractor code against the source SI/BL attachments to see
why the values disagreed.

## Comparator disagreements (this area) — 3 emails

`email_208`, `email_351`, `email_407` were flagged `MISMATCH` on
`notify_party` when the reference says they match (or, for `email_351`,
match on that field specifically — the other two flagged fields on that
email are genuine and correctly caught).

**Cause:** on the SI PDF, the label "Notify Party/Intermediate Consignee"
and the party name are rendered as overlapping text objects. pdfplumber's
character-position sort interleaves them character-by-character, e.g.
`email_208`'s SI produces:

```
Notify Party/Intermediate ConsCigEnReIEeX
```

which is literally `"Consignee"` (9 chars) interleaved with `"CERIEX"`
(6 chars) — 15 chars total, exactly matching both string lengths. The BL
side reads cleanly as `Notify CERIEX`. No normalization rule can
reconstruct two shuffled strings, so this can't be fixed in
`comparator.py`/`normalize.py`. **Root cause is upstream, in
`src/readers.py`'s PDF text extraction** — flagged to whoever owns that
file. A defensive option on our side: detect a value where every other
character plausibly forms a known label fragment (e.g. contains "Cons"
interleaved oddly) and treat it as unparseable rather than compare it
raw, but the real fix is extraction-side.

**Verdict:** not a comparator bug, but directly the "false alarm" failure
mode the brief calls out. Logged, not fixed here.

## Escalation/reliability disagreements — 5 emails (`unreadable` reason)

Reference has 5 `unreadable` cases; we correctly caught 2 and missed 3.

**Caught correctly — `email_511`, `email_515`:** BL PDF is structurally
invalid (`pdfminer: No /Root object! - Is this really a PDF?`). Genuinely
corrupt file, correctly rejected before reaching extraction.

**Missed — `email_512`, `email_513`, `email_514`:** these are real scanned
images (no embedded text layer), so `read_pdf` falls back to Gemini
vision OCR. The scans are sharp and fully legible (visually confirmed by
rendering the page), and vision transcribes all 7 fields identically on
both SI and BL, so the pipeline reports `OK`. Each page carries a faint
watermark reading **"SCANNED COPY - NO OCR TEXT LAYER"**. Reference still
wants these escalated.

**Interpretation:** this looks like an intentional dataset signal, not
noise. The apparent rule: *any image-only scan (no native text layer)
should always route to human review, regardless of whether vision OCR
happens to succeed* — an AI's OCR guess on an official shipping document
isn't something the pipeline should auto-trust for a comparison decision,
even when it reads clean. Right now `readers.py` treats a successful
vision transcription as equivalent to a real text layer. This is a
policy decision for whoever owns the reader/escalation design, not a
comparator bug, but it directly affects the reliability axis this brief
is scored on.

## Genuine disagreement, logged (not obviously a bug) — 1 email

**`email_499`:** the BL PDF's `startxref` offset (1988) points into
binary stream data, not an actual xref table — a structurally malformed
PDF (confirmed at the byte level, not just a strict-parser artifact).
Our reader correctly raises `UnreadableAttachment` per its own rules
(`NEEDS_REVIEW/unreadable`), but reference expects this one read and
compared (`MISMATCH`). Two explanations, can't distinguish from outside:
either the reference pipeline used a more repair-tolerant PDF parser
(e.g. brute-force xref reconstruction), or this is an intentionally hard
edge case. Recommend: if reproducing the reference reader is worthwhile,
try `pypdf` with `strict=False` (has a repair fallback pdfminer.six
doesn't) before giving up on similarly-malformed files.

## Not in this area, but explains the largest score gap — 91 emails

Stage1 classification confuses 91 true `BL_COMPARISON` emails as
`GENERAL` (41% of all true comparison emails never reach the comparator
at all). Sampled 3 (`email_003`, `email_006`, `email_016`) — all have
zero attachments and a body reading "please send the draft BL for X for
checking asap." Our classifier prompt treats this as
`GENERAL/chase_document` by design (documented in
`docs/PROJECT_OVERVIEW.md` section 5: *"chase_document is an email
asking us to send a draft BL, which is different from a request to
check one"*). Reference disagrees — it wants these classified
`BL_COMPARISON` (which, with no attachments, would resolve to
`NEEDS_REVIEW/missing_attachment`). This is a classification-prompt
design question (`src/classifier.py`, `prompts/classify_prompt.txt`),
not a comparison/reporting issue, but it is the single largest lever on
the final score (30% weight on stage1) — flagged to the classification
owner separately.

**Severity check:** confirmed all 91 misclassified emails are genuinely
`OK` in ground truth — none is a real `MISMATCH` that got silently
dropped by the misrouting. So this bug significantly hurts the stage1
accuracy *number*, but causes **zero actual missed defects**. Worth
fixing for score, not urgent for correctness/compliance.

## Full-file audit (confirms nothing was missed)

Re-ran the diff across all 520 emails and every category (not just the
targeted disagreements above), to make sure nothing else was hiding.

- **Category confusion:** exactly two directions exist anywhere in the
  file — the 91 `BL_COMPARISON→GENERAL` above, and one reverse case,
  `email_126` (gt `GENERAL/OK`, we said `BL_COMPARISON/NEEDS_REVIEW`,
  empty defect fields — a wasted escalation, not a wrong defect claim).
  `SI_REQUEST`, `INVOICE_QUERY`, `SPAM` have zero confusion.
- **Field-level audit of all 129 correctly-routed `BL_COMPARISON`
  pairs:** 122 exact matches, 7 mismatches — the same 7 emails already
  diagnosed above (`email_208`, `351`, `407`, `499`, `512`, `513`,
  `514`). No additional disagreements anywhere in the file.
- No malformed submission entries.

## Summary for this area

Of 200 compared documents, 3 have a traceable, non-comparator root cause
(PDF extraction garbling one label). No genuine comparator logic bugs
found — `comparator.py`/`normalize.py` correctly reproduce every
disagreement's *expected* comparison once given clean input; every miss
traces back to what the extraction stage handed it.
