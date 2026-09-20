"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  EmailDetail, FIELDS, FIELD_LABELS, FieldDetail, formatValue, getEmail, retryEmail, submitReview,
} from "@/lib/api";
import { diffWords, Seg } from "@/lib/textdiff";
import { Conf, Pill, useToast } from "@/components/ui";

const REASON_TEXT: Record<string, string> = {
  missing_attachment: "The SI and/or the BL was not attached.",
  wrong_doc_type: "The second attachment is not a Bill of Lading.",
  unreadable: "An attachment could not be read (scanned, empty or corrupt).",
  missing_value: "A required field is blank in a source document.",
};

type Side = "si" | "bl";
type Focus = { side: Side; snippet: string } | null;

function ValueCell({ field, value, det, segs, onSnippet }: {
  field: string; value: string | number | null | undefined; det?: FieldDetail; segs?: Seg[]; onSnippet: (snippet: string) => void;
}) {
  const text = formatValue(field, value);
  if (!text) {
    return <span className="absent">{det ? (det.label_found ? "Blank in the document" : "Not in the document") : "-"}</span>;
  }
  return (
    <>
      <span className="val">
        {segs
          ? segs.map((s, i) => <span key={i}>{i ? " " : ""}{s.diff ? <mark className="d">{s.text}</mark> : s.text}</span>)
          : text}
      </span>{" "}
      {det && <Conf d={det} />}
      {det?.snippet && (
        <button className="snip" title="Show this line in the source document" onClick={() => onSnippet(det.snippet as string)}>
          {det.snippet}
        </button>
      )}
    </>
  );
}

function FieldTable({ d, defects, onFocus }: {
  d: NonNullable<EmailDetail["detail"]>; defects: string[]; onFocus: (side: Side, snippet: string) => void;
}) {
  if (!d.si_fields || !d.bl_fields) return null;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Field</th><th>SI value</th><th>BL value</th><th>Result</th></tr></thead>
          <tbody>
            {FIELDS.map((f) => {
              const si = d.si_detail?.[f], bl = d.bl_detail?.[f];
              const siText = formatValue(f, d.si_fields?.[f]), blText = formatValue(f, d.bl_fields?.[f]);
              const differs = defects.includes(f);
              const diff = differs && siText && blText ? diffWords(siText, blText) : null;
              const low = (si && si.normalized !== null && si.confidence < 0.6) || (bl && bl.normalized !== null && bl.confidence < 0.6);
              return (
                <tr key={f} className={differs ? "diff" : ""}>
                  <td>{FIELD_LABELS[f]}</td>
                  <td><ValueCell field={f} value={d.si_fields?.[f]} det={si} segs={diff?.left} onSnippet={(s) => onFocus("si", s)} /></td>
                  <td><ValueCell field={f} value={d.bl_fields?.[f]} det={bl} segs={diff?.right} onSnippet={(s) => onFocus("bl", s)} /></td>
                  <td>
                    {differs ? "MISMATCH" : "match"}
                    {low && <div><span className="chip warn">low confidence</span></div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {d.si_detail && (
        <p className="meta legend">
          Confidence shows how sure the extractor is: the label was found, the source line really contains the value, and
          the value looks valid. <span className="conf hi">80%+</span> <span className="conf mid">50-79%</span> <span className="conf lo">below 50%</span>
          {" "}Click a grey source line to see it in the document.
        </p>
      )}
    </>
  );
}

/** The document text, with the line a value was read from highlighted and scrolled into view. */
function Highlighted({ text, snippet }: { text: string; snippet: string | null }) {
  const ref = useRef<HTMLPreElement>(null);
  const at = snippet ? text.indexOf(snippet) : -1;
  useEffect(() => {
    const pre = ref.current;
    const mark = pre?.querySelector("mark") as HTMLElement | null | undefined;
    if (pre && mark) pre.scrollTop = Math.max(0, mark.offsetTop - pre.clientHeight / 2);
  }, [text, snippet, at]);
  if (at < 0 || !snippet) return <pre ref={ref}>{text}</pre>;
  return <pre ref={ref}>{text.slice(0, at)}<mark>{snippet}</mark>{text.slice(at + snippet.length)}</pre>;
}

function ReviewForm({ item, onSaved, onNext }: { item: EmailDetail; onSaved: () => void; onNext?: () => void }) {
  const toast = useToast();
  const prior = item.human_decision;
  const [status, setStatus] = useState(prior?.status ?? (item.status === "MISMATCH" ? "MISMATCH" : "OK"));
  const [fields, setFields] = useState<string[]>(prior?.defect_fields ?? item.defect_fields);
  const [note, setNote] = useState(prior?.note ?? "");
  const [busy, setBusy] = useState(false);

  const toggle = (f: string) => setFields((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  async function save(thenNext: boolean) {
    setBusy(true);
    try {
      await submitReview(item.email_id, { status, defect_fields: status === "MISMATCH" ? fields : [], note });
      toast("Decision saved. The report now uses it.", "ok");
      onSaved();
      if (thenNext && onNext) onNext();
    } catch (e) {
      toast(`Could not save: ${(e as Error).message}`, "bad");
    } finally { setBusy(false); }
  }

  async function retry() {
    setBusy(true);
    try { await retryEmail(item.email_id); toast("Retry queued. Refresh the list in a moment."); }
    catch (e) { toast(`Could not retry: ${(e as Error).message}`, "bad"); }
    finally { setBusy(false); }
  }

  return (
    <div className="review">
      <b>Human review</b>
      {prior && <div className="meta">Previously decided: {prior.status}{prior.note ? ` - ${prior.note}` : ""}</div>}
      <div className="row" style={{ marginTop: 8 }}>
        <label><input type="radio" checked={status === "OK"} onChange={() => setStatus("OK")} /> No mismatch</label>
        <label><input type="radio" checked={status === "MISMATCH"} onChange={() => setStatus("MISMATCH")} /> Mismatch</label>
      </div>
      {status === "MISMATCH" && (
        <div>{FIELDS.map((f) => (
          <label key={f}><input type="checkbox" checked={fields.includes(f)} onChange={() => toggle(f)} /> {FIELD_LABELS[f]}</label>
        ))}</div>
      )}
      <textarea placeholder="Note (why you decided this)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button disabled={busy} onClick={() => save(false)}>Save decision</button>
        {onNext && <button disabled={busy} onClick={() => save(true)}>Save and next</button>}
        <button className="secondary" disabled={busy} onClick={retry}>Retry processing</button>
      </div>
    </div>
  );
}

export function Detail({ id, onChanged, onClose, onNext }: {
  id: string; onChanged: () => void; onClose: () => void; onNext?: () => void;
}) {
  const [item, setItem] = useState<EmailDetail | null>(null);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<Focus>(null);
  const [srcOpen, setSrcOpen] = useState(false);
  const [fullText, setFullText] = useState(false);   // show the whole SI/BL text instead of a scrolling box

  const load = useCallback(() => {
    setError("");
    getEmail(id).then((e) => { setItem(e); setSrcOpen(e.status === "NEEDS_REVIEW"); }).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => { setItem(null); setFocus(null); load(); }, [load]);

  if (error) {
    return (
      <div className="panel">
        <button className="icon-btn" aria-label="Close details" onClick={onClose}>×</button>
        <div className="alert bad">Could not load {id}: {error}</div>
      </div>
    );
  }
  if (!item) {
    return (
      <div className="panel" aria-busy="true">
        <div className="skeleton" style={{ height: 24, width: "60%", marginBottom: 10 }} />
        <div className="skeleton" style={{ height: 14, width: "40%", marginBottom: 18 }} />
        <div className="skeleton" style={{ height: 220 }} />
      </div>
    );
  }

  const d = item.detail;
  const isComparison = item.category === "BL_COMPARISON";
  const lowFields = d ? FIELDS.flatMap((f) => (["si", "bl"] as Side[]).flatMap((side) => {
    const det = (side === "si" ? d.si_detail : d.bl_detail)?.[f];
    return det && det.normalized !== null && det.confidence < 0.6 ? [`${FIELD_LABELS[f]} (${side.toUpperCase()} ${Math.round(det.confidence * 100)}%)`] : [];
  })) : [];

  return (
    <div className="panel">
      <button className="icon-btn" aria-label="Close details" title="Close (Esc)" onClick={onClose}>×</button>
      <h3>{item.title || item.subject}</h3>
      <div className="meta">
        {item.email_id} · from {item.email.from} · {item.category} / {item.intent ?? "-"} · <Pill status={item.status} />
        <br />Original subject: {item.email.subject}
      </div>
      {item.human_decision && <div className="alert ok">A person set this result to {item.human_decision.status}.</div>}
      {item.review_reason && !item.human_decision && (
        <div className="alert warn"><b>Needs a human decision:</b> {REASON_TEXT[item.review_reason] ?? item.review_reason} ({item.review_reason})</div>
      )}
      {lowFields.length > 0 && <div className="alert warn"><b>Please double-check:</b> low confidence on {lowFields.join(", ")}.</div>}
      {item.detail_error && <div className="alert bad">Could not load the SI/BL fields: {item.detail_error}</div>}
      {isComparison && d && d.si_fields && d.bl_fields && (
        <>
          {item.status === "MISMATCH"
            ? <div className="alert bad">SI and BL differ on: {item.defect_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</div>
            : item.status === "OK" && <div className="alert ok">No mismatch detected.</div>}
          <FieldTable d={d} defects={item.defect_fields} onFocus={(side, snippet) => { setFocus({ side, snippet }); setSrcOpen(true); }} />
        </>
      )}
      {isComparison && d && (d.si_text || d.bl_text) && (
        <details open={srcOpen} onToggle={(e) => setSrcOpen(e.currentTarget.open)}>
          <summary>Source documents{focus ? ` - showing the line read for the ${focus.side.toUpperCase()}` : ""}</summary>
          <div className="row" style={{ margin: "6px 0" }}>
            <button className="secondary" onClick={() => setFullText((v) => !v)}>{fullText ? "Use a scrolling box" : "Show full text"}</button>
            <span className="muted small">The SI and BL sit side by side when there is room, and stack when there is not.</span>
          </div>
          <div className={`two ${fullText ? "full" : ""}`}>
            <div><div className="meta">SI text</div>
              {d.si_text ? <Highlighted text={d.si_text} snippet={focus?.side === "si" ? focus.snippet : null} /> : <pre>not available</pre>}</div>
            <div><div className="meta">BL text</div>
              {d.bl_text ? <Highlighted text={d.bl_text} snippet={focus?.side === "bl" ? focus.snippet : null} /> : <pre>not available</pre>}</div>
          </div>
        </details>
      )}
      <details>
        <summary>Email body</summary>
        <pre>{item.email.body}</pre>
      </details>
      {isComparison && (
        <ReviewForm
          key={item.email_id + (item.human_decision?.status ?? "")}
          item={item}
          onSaved={() => { load(); onChanged(); }}
          onNext={onNext}
        />
      )}
    </div>
  );
}
