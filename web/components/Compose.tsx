"use client";

import { KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FIELD_LABELS } from "@/lib/api";
import { SAMPLES } from "@/lib/samples";
import {
  SecondOpinion, SimAttachment, SimEntry, SimInfo, SimStatus, deleteSimEmail, fileToBase64, getSimStatus, sendSimEmail, textToBase64,
} from "@/lib/tools";
import { Pill, useToast } from "@/components/ui";

type Slot = { mode: "text" | "file"; text: string; file: { name: string; size: number; base64: string } | null };
const emptySlot = (): Slot => ({ mode: "text", text: "", file: null });
const slotFilled = (s: Slot) => (s.mode === "text" ? s.text.trim().length > 0 : s.file !== null);
const kb = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

const POLL_MS = 1200, GIVE_UP_MS = 90_000;
const DEFAULT_FROM = "ops@northwind-paper.example";

function SlotEditor({ title, help, slot, onChange, allowed, maxMb }: {
  title: string; help: string; slot: Slot; onChange: (s: Slot) => void; allowed: string[]; maxMb: number;
}) {
  const [problem, setProblem] = useState("");
  const [over, setOver] = useState(false);

  async function take(file: File | undefined) {
    if (!file) return;
    setProblem("");
    if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) { setProblem(`Only ${allowed.join(", ")} files can be attached.`); return; }
    if (file.size > maxMb * 1024 * 1024) { setProblem(`That file is larger than ${maxMb} MB.`); return; }
    onChange({ ...slot, mode: "file", file: { name: file.name, size: file.size, base64: await fileToBase64(file) } });
  }

  return (
    <fieldset className="slot">
      <legend>{title}</legend>
      <div className="seg" role="group" aria-label={`${title}: how to provide it`}>
        <button type="button" className={slot.mode === "text" ? "active" : ""} aria-pressed={slot.mode === "text"} onClick={() => onChange({ ...slot, mode: "text" })}>Type or paste</button>
        <button type="button" className={slot.mode === "file" ? "active" : ""} aria-pressed={slot.mode === "file"} onClick={() => onChange({ ...slot, mode: "file" })}>Upload a file</button>
      </div>
      {slot.mode === "text" ? (
        <textarea className="mono-input" rows={9} value={slot.text} aria-label={`${title} text`} placeholder={help}
          onChange={(e) => onChange({ ...slot, text: e.target.value })} spellCheck={false} />
      ) : slot.file ? (
        <div className="file-card">
          <div><b>{slot.file.name}</b><div className="muted small">{kb(slot.file.size)}</div></div>
          <button type="button" className="secondary" onClick={() => onChange({ ...slot, file: null })}>Remove</button>
        </div>
      ) : (
        <label className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files[0]); }}>
          <input type="file" accept={allowed.join(",")} onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
          <span><b>Choose a file</b> or drop it here</span>
          <span className="muted small">{allowed.join(", ")} · up to {maxMb} MB</span>
        </label>
      )}
      {problem && <div className="alert bad" role="alert" style={{ margin: "8px 0 0" }}>{problem}</div>}
    </fieldset>
  );
}

/** What the system did with the email, in plain steps. Built from the stored result, so nothing here is invented. */
function Outcome({ entry, subject, opinion }: { entry: SimEntry; subject: string; opinion?: SecondOpinion | null }) {
  const comparison = entry.category === "BL_COMPARISON";
  const why: Record<string, string> = {
    missing_attachment: "The SI and/or the BL was not attached.",
    wrong_doc_type: "The second attachment is not a Bill of Lading.",
    unreadable: "An attachment could not be read (empty, corrupt or scanned).",
    missing_value: "A required field is blank in a document.",
  };
  return (
    <ol className="steps-list">
      <li className="done"><b>Received</b><span>Your email &ldquo;{subject || "(no subject)"}&rdquo; is in the inbox.</span></li>
      <li className="done"><b>Classified</b>
        <span><span className="chip">{entry.category.replace("_", " ")}</span> <span className="chip">{entry.intent ?? "-"}</span> Gemini&apos;s title for it: {entry.title}</span></li>
      {comparison ? (
        <>
          <li className={entry.review_reason && entry.review_reason !== "missing_value" ? "stop" : "done"}><b>Read the documents</b>
            <span>{entry.review_reason && entry.review_reason !== "missing_value" ? why[entry.review_reason] : "Both documents were read and the 7 fields extracted."}</span></li>
          {opinion && (
            <li className={opinion.agree === opinion.checked ? "done" : "stop"}><b>Second opinion from Gemini</b>
              <span>Gemini read both documents on its own and matched {opinion.agree} of {opinion.checked} values
                {opinion.agree === opinion.checked ? "." : `: it read ${opinion.disagreements.map((d) => `${d.side.toUpperCase()} ${FIELD_LABELS[d.field] ?? d.field}`).join(", ")} differently.`}</span></li>
          )}
          <li className={entry.review_reason ? "stop" : "done"}><b>Compared and decided</b>
            <span>
              <Pill status={entry.status} />{" "}
              {entry.status === "MISMATCH" && <>They differ on {entry.defect_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}.</>}
              {entry.status === "OK" && <>Every field matches: no person needed.</>}
              {entry.status === "NEEDS_REVIEW" && <>Sent to a person. {entry.review_reason ? why[entry.review_reason] : ""}</>}
            </span></li>
        </>
      ) : (
        <li className="done"><b>Filed</b><span>Only document comparisons are checked further. This one is filed as {entry.category.replace("_", " ").toLowerCase()}.</span></li>
      )}
    </ol>
  );
}

export function Compose({ info, onClose, onOpenEmail, onChanged }: {
  info: SimInfo; onClose: () => void; onOpenEmail: (id: string) => void; onChanged: () => void;
}) {
  const toast = useToast();
  const [from, setFrom] = useState(DEFAULT_FROM);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [si, setSi] = useState<Slot>(emptySlot());
  const [bl, setBl] = useState<Slot>(emptySlot());
  const [phase, setPhase] = useState<"draft" | "working" | "result" | "failed">("draft");
  const [error, setError] = useState("");
  const [sent, setSent] = useState<{ id: string; status: SimStatus | null } | null>(null);
  const [origin, setOrigin] = useState("");   // "" = blank, an example's id, or "custom" once an example has been edited
  const sample = SAMPLES.find((s) => s.id === origin) ?? null;
  const touch = () => setOrigin((o) => (o && o !== "custom" ? "custom" : o));   // any edit makes it your own email
  const dialog = useRef<HTMLDivElement>(null);
  const firstField = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dirty = !!(subject || body || slotFilled(si) || slotFilled(bl));
  const canSend = phase === "draft" && (subject.trim() || body.trim());
  const slotCount = useMemo(() => [si, bl].filter(slotFilled).length, [si, bl]);

  // Focus the first field on open, and hand focus back to whatever opened the window when it closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    firstField.current?.focus();
    return () => { opener?.focus?.(); if (timer.current) clearTimeout(timer.current); };
  }, []);

  const close = useCallback(() => {
    if (phase === "draft" && dirty && !window.confirm("Discard this draft?")) return;
    onClose();
  }, [phase, dirty, onClose]);

  // Esc closes; Tab stays inside the window. The page's own shortcuts (j, k, /, c) must not fire behind it.
  function onKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    e.nativeEvent.stopPropagation();
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab" || !dialog.current) return;
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])')]
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function clearAll() {
    setOrigin(""); setFrom(DEFAULT_FROM); setSubject(""); setBody(""); setSi(emptySlot()); setBl(emptySlot());
  }

  function loadSample(id: string) {
    const s = SAMPLES.find((x) => x.id === id);
    if (!s) { clearAll(); return; }
    setOrigin(s.id);
    setFrom(s.from); setSubject(s.subject); setBody(s.body);
    setSi(s.si ? { mode: "text", text: s.si, file: null } : emptySlot());
    setBl(s.bl ? { mode: "text", text: s.bl, file: null } : emptySlot());
  }

  async function send() {
    setError("");
    const files: SimAttachment[] = [];
    if (slotFilled(si)) files.push(si.mode === "text" ? { filename: "SI.txt", content_base64: textToBase64(si.text) } : { filename: si.file!.name, content_base64: si.file!.base64 });
    if (slotFilled(bl)) files.push(bl.mode === "text" ? { filename: "BL.txt", content_base64: textToBase64(bl.text) } : { filename: bl.file!.name, content_base64: bl.file!.base64 });
    setPhase("working");
    try {
      const { email_id } = await sendSimEmail({ from: from.trim(), subject: subject.trim(), body: body.trim(), attachments: files });
      setSent({ id: email_id, status: null });
      const started = Date.now();
      const poll = async () => {
        try {
          const s = await getSimStatus(email_id);
          if (s.state === "done") { setSent({ id: email_id, status: s }); setPhase("result"); onChanged(); return; }
          if (s.state === "failed") { setError(s.error ?? "Processing failed."); setPhase("failed"); return; }
        } catch (e) { setError((e as Error).message); setPhase("failed"); return; }
        if (Date.now() - started > GIVE_UP_MS) { setError("This is taking longer than expected. Check the inbox in a minute."); setPhase("failed"); return; }
        timer.current = setTimeout(poll, POLL_MS);
      };
      timer.current = setTimeout(poll, POLL_MS);
    } catch (e) { setError((e as Error).message); setPhase("failed"); }
  }

  async function discard() {
    if (!sent) return;
    try { await deleteSimEmail(sent.id); toast("Test email deleted.", "ok"); onChanged(); onClose(); }
    catch (e) { toast(`Could not delete: ${(e as Error).message}`, "bad"); }
  }

  const backToDraft = () => { setSent(null); setError(""); setPhase("draft"); };   // keeps what you wrote
  const writeAnother = () => { clearAll(); backToDraft(); };                       // a fresh, blank email

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="compose-title" ref={dialog} onKeyDown={onKeyDown}>
        <div className="modal-head">
          <h2 id="compose-title">New email</h2>
          <button className="strip-close" aria-label="Close" title="Close (Esc)" onClick={close}>×</button>
        </div>

        {phase === "draft" && (
          <>
            <div className="modal-body">
              <div className="compose-grid">
                <div className="compose-mail">
                  <label className="field"><span>Start from an example</span>
                    <div className="row" style={{ flexWrap: "nowrap" }}>
                      <select value={origin} onChange={(e) => loadSample(e.target.value)} aria-describedby="sample-expect">
                        <option value="">Blank email</option>
                        {SAMPLES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                        {origin === "custom" && <option value="custom" disabled>Your own email (edited)</option>}
                      </select>
                      <button type="button" className="secondary" disabled={!dirty} onClick={clearAll}>Clear</button>
                    </div>
                  </label>
                  <p id="sample-expect" className="muted small" style={{ margin: "-4px 0 8px" }}>
                    {sample ? `Expected: ${sample.expect}` : origin === "custom" ? "You changed the example, so this is now your own email." : "Or write your own below."}
                  </p>
                  <label className="field"><span>From</span><input ref={firstField} type="text" value={from} onChange={(e) => { setFrom(e.target.value); touch(); }} maxLength={200} /></label>
                  <label className="field"><span>Subject</span><input type="text" value={subject} onChange={(e) => { setSubject(e.target.value); touch(); }} maxLength={300} placeholder="e.g. Check draft BL vs SI - PO 12345" /></label>
                  <label className="field"><span>Message</span><textarea rows={9} value={body} onChange={(e) => { setBody(e.target.value); touch(); }} placeholder="Dear team, please check the attached SI against the draft BL." /></label>
                </div>
                <div className="compose-files">
                  <SlotEditor title="Attachment 1: Shipping Instruction (SI)" slot={si} onChange={(s) => { setSi(s); touch(); }} allowed={info.allowed} maxMb={info.max_file_mb}
                    help={"Shipper/Exporter: ACME LTD\nCONSIGNEE: BETA CO\nNOTIFY PARTY: BETA CO\nPort of Loading: SINGAPORE\nDischarge Port: KARACHI\nNo. of Containers or Packages: 2 x 40'HC\nGross Weight (KG): 42,000 KG"} />
                  <SlotEditor title="Attachment 2: draft Bill of Lading (BL)" slot={bl} onChange={(s) => { setBl(s); touch(); }} allowed={info.allowed} maxMb={info.max_file_mb}
                    help={"SHIPPER: ACME LTD\nCONSIGNEE: BETA CO\nNotify: BETA CO\nPort of Loading (POL): SINGAPORE\nPOD: KARACHI\nContainer Count: 2 x 40'HC\nGross Wt (kgs): 42,000 KG"} />
                  <p className="muted small">The system reads the first two attachments as the SI, then the BL. Leave one out to see how it reacts.</p>
                </div>
              </div>
            </div>
            <div className="modal-foot">
              <span className="muted small">Uses 1 to 3 Gemini calls. Test emails are tagged <i className="chip">Simulated</i> and never enter the official submission. {slotCount} of 2 documents attached.</span>
              <div className="row">
                <button className="secondary" onClick={close}>Cancel</button>
                <button disabled={!canSend} onClick={send}>Send to inbox</button>
              </div>
            </div>
          </>
        )}

        {phase === "working" && (
          <div className="modal-body" aria-live="polite">
            <ol className="steps-list">
              <li className="done"><b>Received</b><span>The email is in the inbox.</span></li>
              <li className="busy"><b>Processing</b><span><i className="spinner" aria-hidden="true" /> Gemini is classifying it, reading the documents and giving its second opinion. This takes about 10 to 20 seconds.</span></li>
            </ol>
          </div>
        )}

        {phase === "result" && sent?.status?.entry && (
          <>
            <div className="modal-body">
              <div className="alert ok" role="status"><b>{sent.id}</b> was processed.</div>
              <Outcome entry={sent.status.entry} subject={subject.trim()} opinion={sent.status.second_opinion} />
            </div>
            <div className="modal-foot">
              <button className="secondary" onClick={discard}>Delete this test email</button>
              <div className="row">
                <button className="secondary" onClick={writeAnother}>Write another</button>
                <button onClick={() => { onOpenEmail(sent.id); onClose(); }}>Open in inbox</button>
              </div>
            </div>
          </>
        )}

        {phase === "failed" && (
          <>
            <div className="modal-body"><div className="alert bad" role="alert"><b>Could not process this email.</b> {error}</div>
              <p className="muted small">Nothing was added to the inbox. Your draft is still here: fix it and send again.</p></div>
            <div className="modal-foot"><span /><div className="row"><button className="secondary" onClick={onClose}>Close</button><button onClick={backToDraft}>Back to the draft</button></div></div>
          </>
        )}
      </div>
    </div>
  );
}
