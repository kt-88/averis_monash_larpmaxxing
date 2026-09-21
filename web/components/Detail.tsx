"use client";

import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  DECISION_REASONS, EmailDetail, FIELDS, FIELD_LABELS, FieldDetail, formatValue, getEmail, retryEmail, submitReview,
} from "@/lib/api";
import { diffWords, Seg } from "@/lib/textdiff";
import { Pill, useToast } from "@/components/ui";

const REASON_TEXT: Record<string, string> = {
  missing_attachment: "The SI and/or the BL was not attached.",
  wrong_doc_type: "The second attachment is not a Bill of Lading.",
  unreadable: "An attachment could not be read (scanned, empty or corrupt).",
  missing_value: "A required field is blank in a source document.",
};

type Side = "si" | "bl";
type Focus = { side: Side; snippet: string } | null;
type TabKey = "details" | "sources" | "body" | "review";

/** Left/right/home/end move between the tabs, as in any tab strip. */
function moveTab(e: ReactKeyboardEvent<HTMLDivElement>, keys: TabKey[], active: TabKey, go: (k: TabKey) => void) {
  const i = keys.indexOf(active);
  const to = e.key === "ArrowRight" ? keys[(i + 1) % keys.length]
    : e.key === "ArrowLeft" ? keys[(i - 1 + keys.length) % keys.length]
    : e.key === "Home" ? keys[0] : e.key === "End" ? keys[keys.length - 1] : null;
  if (!to) return;
  e.preventDefault();
  go(to);
  document.getElementById(`tab-${to}`)?.focus();
}

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
              return (
                <tr key={f} className={differs ? "diff" : ""}>
                  <td>{FIELD_LABELS[f]}</td>
                  <td><ValueCell field={f} value={d.si_fields?.[f]} det={si} segs={diff?.left} onSnippet={(s) => onFocus("si", s)} /></td>
                  <td><ValueCell field={f} value={d.bl_fields?.[f]} det={bl} segs={diff?.right} onSnippet={(s) => onFocus("bl", s)} /></td>
                  <td>
                    {differs ? "MISMATCH" : "match"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {d.si_detail && <p className="meta legend">Click a grey source line to see it in the document.</p>}
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

/** A checkbox or radio drawn as a pill (or, with `box`, a rounded rectangle). The real input stays in the page
 *  (visually hidden) for keyboard and screen readers. */
function Toggle({ type, checked, onChange, children, box }: {
  type: "radio" | "checkbox"; checked: boolean; onChange: () => void; children: ReactNode; box?: boolean;
}) {
  return (
    <label className={box ? "toggle box" : "toggle"}>
      <input type={type} checked={checked} onChange={onChange} />
      <span>{children}</span>
    </label>
  );
}

function ReviewForm({ item, onSaved, onNext }: { item: EmailDetail; onSaved: () => void; onNext?: () => void }) {
  const toast = useToast();
  const prior = item.human_decision;
  const [status, setStatus] = useState(prior?.status ?? (item.status === "MISMATCH" ? "MISMATCH" : "OK"));
  const [fields, setFields] = useState<string[]>(prior?.defect_fields ?? item.defect_fields);
  const [note, setNote] = useState(prior?.note ?? "");
  const [reason, setReason] = useState<string>(prior?.reason ?? "");
  const [busy, setBusy] = useState(false);

  // Blank SI fields the BL fills in: the only blanks a reviewer can accept (a blank BL is never accepted).
  const d = item.detail;
  const blankOnSi = FIELDS.filter((f) => d?.si_fields && d?.bl_fields
    && (d.si_fields[f] === null || d.si_fields[f] === "BLANK") && d.bl_fields[f] !== null && d.bl_fields[f] !== "BLANK");
  const [accepted, setAccepted] = useState<string[]>(prior?.accepted_blanks?.length ? prior.accepted_blanks : blankOnSi);
  const needsReason = !!item.review_reason;   // the system asked for this review, so say why

  const toggle = (f: string) => setFields((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));
  const toggleBlank = (f: string) => setAccepted((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  async function save(thenNext: boolean) {
    setBusy(true);
    try {
      await submitReview(item.email_id, {
        status, defect_fields: status === "MISMATCH" ? fields : [], note,
        reason: reason || null, accepted_blanks: reason === "blank_acceptable" ? accepted : [],
      });
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
      <div className="pills" role="radiogroup" aria-label="Result">
        <Toggle box type="radio" checked={status === "OK"} onChange={() => setStatus("OK")}>No mismatch</Toggle>
        <Toggle box type="radio" checked={status === "MISMATCH"} onChange={() => setStatus("MISMATCH")}>Mismatch</Toggle>
      </div>
      {status === "MISMATCH" && (
        <div className="pills fields" aria-label="Mismatched fields">{FIELDS.map((f) => (
          <Toggle key={f} type="checkbox" checked={fields.includes(f)} onChange={() => toggle(f)}>{FIELD_LABELS[f]}</Toggle>
        ))}</div>
      )}
      {needsReason && (
        <div style={{ marginTop: 8 }}>
          <div className="meta">Why? This teaches the system, so similar cases can skip review.</div>
          <div className="pills" role="radiogroup" aria-label="Reason">
            {Object.entries(DECISION_REASONS)
              .filter(([k]) => k !== "blank_acceptable" || (item.review_reason === "missing_value" && blankOnSi.length > 0))
              .map(([k, label]) => (
                <Toggle key={k} type="radio" checked={reason === k} onChange={() => setReason(k)}>{label}</Toggle>
              ))}
          </div>
          {reason === "blank_acceptable" && (
            <>
              <div className="meta">Accept the blank SI value for:</div>
              <div className="pills" aria-label="Accepted blank fields">
                {blankOnSi.map((f) => (
                  <Toggle key={f} type="checkbox" checked={accepted.includes(f)} onChange={() => toggleBlank(f)}>{FIELD_LABELS[f]}</Toggle>
                ))}
              </div>
              <div className="meta">The system only stops escalating a field after several reviewers agree.</div>
            </>
          )}
        </div>
      )}
      <textarea placeholder="Note (why you decided this)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button disabled={busy || (needsReason && !reason)} onClick={() => save(false)}>Save decision</button>
        {onNext && <button disabled={busy || (needsReason && !reason)} onClick={() => save(true)}>Save and next</button>}
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
  const [tab, setTab] = useState<TabKey>("details");
  const [fullText, setFullText] = useState(false);   // show the whole SI/BL text instead of a scrolling box

  const load = useCallback(() => {
    setError("");
    getEmail(id).then((e) => setItem(e)).catch((e) => setError(e.message));
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
  const hasSources = isComparison && !!d && !!(d.si_text || d.bl_text);
  const needsDecision = !!item.review_reason && !item.human_decision;
  const tabs: { key: TabKey; label: string }[] = [
    { key: "details", label: "Details" },
    ...(hasSources ? [{ key: "sources" as const, label: "Source documents" }] : []),
    { key: "body", label: "Email body" },
    ...(isComparison ? [{ key: "review" as const, label: "Human review" }] : []),
  ];
  const active: TabKey = tabs.some((t) => t.key === tab) ? tab : "details";
  const panelProps = (key: TabKey) => ({ role: "tabpanel", id: `panel-${key}`, "aria-labelledby": `tab-${key}`, hidden: active !== key });

  return (
    <div className="panel tabbed">
      <div className="tabstrip" role="tablist" aria-label="Email sections"
        onKeyDown={(e) => moveTab(e, tabs.map((t) => t.key), active, setTab)}>
        {tabs.map((t) => (
          <button key={t.key} id={`tab-${t.key}`} role="tab" aria-selected={active === t.key} aria-controls={`panel-${t.key}`}
            tabIndex={active === t.key ? 0 : -1} className={`ptab ${active === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
            {t.key === "review" && needsDecision && <i className="dot warn" title="Needs a human decision" />}
          </button>
        ))}
        <button className="strip-close" aria-label="Close details" title="Close (Esc)" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">
        <h3>{item.title || item.subject}</h3>
        {item.human_decision && <div className="alert ok">A person set this result to {item.human_decision.status}.</div>}
        {needsDecision && (
          <div className="alert warn"><b>Needs a human decision:</b> {REASON_TEXT[item.review_reason as string] ?? item.review_reason} ({item.review_reason})</div>
        )}

        <div {...panelProps("details")}>
          <div className="meta">
            {item.email_id} · from {item.email.from} · {item.category} / {item.intent ?? "-"} · <Pill status={item.status} />
            <br />Original subject: {item.email.subject}
          </div>
          {!!d?.learned_exceptions?.length && (
            <div className="alert ok">
              Resolved without review using what reviewers taught the system: a blank SI value was accepted for{" "}
              {d.learned_exceptions.map((f) => FIELD_LABELS[f] ?? f).join(", ")} (the BL has it).
            </div>
          )}
          {item.detail_error && <div className="alert bad">Could not load the SI/BL fields: {item.detail_error}</div>}
          {isComparison && d && d.si_fields && d.bl_fields && (
            <>
              {item.status === "MISMATCH"
                ? <div className="alert bad">SI and BL differ on: {item.defect_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</div>
                : item.status === "OK" && <div className="alert ok">No mismatch detected.</div>}
              <FieldTable d={d} defects={item.defect_fields} onFocus={(side, snippet) => { setFocus({ side, snippet }); setTab("sources"); }} />
            </>
          )}
        </div>

        {hasSources && d && (
          <div {...panelProps("sources")}>
            <div className="row" style={{ margin: "0 0 8px" }}>
              <button className="secondary" onClick={() => setFullText((v) => !v)}>{fullText ? "Use a scrolling box" : "Show full text"}</button>
              <span className="muted small">
                {focus ? `Showing the line read for the ${focus.side.toUpperCase()}. ` : ""}The SI and BL sit side by side when there is room.
              </span>
            </div>
            <div className={`two ${fullText ? "full" : ""}`}>
              <div><div className="meta">SI text</div>
                {d.si_text ? <Highlighted text={d.si_text} snippet={focus?.side === "si" ? focus.snippet : null} /> : <pre>not available</pre>}</div>
              <div><div className="meta">BL text</div>
                {d.bl_text ? <Highlighted text={d.bl_text} snippet={focus?.side === "bl" ? focus.snippet : null} /> : <pre>not available</pre>}</div>
            </div>
          </div>
        )}

        <div {...panelProps("body")}>
          <pre>{item.email.body}</pre>
        </div>

        {isComparison && (
          <div {...panelProps("review")}>
            <ReviewForm
              key={item.email_id + (item.human_decision?.status ?? "")}
              item={item}
              onSaved={() => { load(); onChanged(); }}
              onNext={onNext}
            />
          </div>
        )}
      </div>
    </div>
  );
}
