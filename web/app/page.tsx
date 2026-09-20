"use client";

import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CATEGORIES, EmailDetail, EmailRow, FIELDS, FIELD_LABELS, FieldDetail, RunStatus, STATUSES,
  formatValue, getEmail, getEmails, getHealth, getRun, retryEmail, startRun, submitReview,
} from "@/lib/api";

const REASON_TEXT: Record<string, string> = {
  missing_attachment: "The SI and/or the BL was not attached.",
  wrong_doc_type: "The second attachment is not a Bill of Lading.",
  unreadable: "An attachment could not be read (scanned, empty or corrupt).",
  missing_value: "A required field is blank in a source document.",
};

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "MISMATCH", label: "Mismatch" },
  { key: "NEEDS_REVIEW", label: "Needs review" },
  { key: "OK", label: "OK" },
];

function Pill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{status.replace("_", " ")}</span>;
}

/** Confidence badge: green >= 80%, amber 50-79%, red below. The tooltip shows the source line. */
function Conf({ d }: { d: FieldDetail }) {
  const level = d.confidence >= 0.8 ? "hi" : d.confidence >= 0.5 ? "mid" : "lo";
  return (
    <span className={`conf ${level}`} title={d.snippet ? `Read from: ${d.snippet}` : "No source line"}>
      {Math.round(d.confidence * 100)}%
    </span>
  );
}

/** What was wrong with this email, at a glance: the mismatched fields, or the reason it needs a person. */
function Issue({ r }: { r: EmailRow }) {
  return (
    <>
      {r.status === "MISMATCH" && r.defect_fields.map((f) => <span key={f} className="chip bad">{FIELD_LABELS[f] ?? f}</span>)}
      {r.status === "NEEDS_REVIEW" && <span className="chip warn">{(r.review_reason ?? "review").replace(/_/g, " ")}</span>}
      {r.human_decision && <span className="chip">person decided</span>}
      {r.status === "OK" && !r.human_decision && <span className="muted">-</span>}
    </>
  );
}

function EmailTable({ rows, selected, onPick, empty, maxHeight }: {
  rows: EmailRow[]; selected: string | null; onPick: (id: string) => void; empty: string; maxHeight: string;
}) {
  if (!rows.length) return <div className="table-wrap"><div className="empty">{empty}</div></div>;

  // Keyboard: Enter/Space opens the email, arrow keys move between rows.
  function onKey(e: KeyboardEvent<HTMLTableRowElement>, id: string) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(id); }
    else if (e.key === "ArrowDown") { e.preventDefault(); (e.currentTarget.nextElementSibling as HTMLElement | null)?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (e.currentTarget.previousElementSibling as HTMLElement | null)?.focus(); }
  }

  return (
    <div className="table-wrap scroll" style={{ maxHeight }}>
      <table>
        <thead><tr><th>ID</th><th>Email</th><th>Status</th><th>Issue</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.email_id}
              tabIndex={0}
              aria-selected={selected === r.email_id}
              className={selected === r.email_id ? "sel" : ""}
              onClick={() => onPick(r.email_id)}
              onKeyDown={(e) => onKey(e, r.email_id)}
            >
              <td className="mono">{r.email_id.replace("email_", "")}</td>
              <td>
                <div className="clip">{r.title || r.subject}</div>
                <div className="muted small">{r.category.replace("_", " ")} · {r.intent ?? "-"}</div>
              </td>
              <td><Pill status={r.status} /></td>
              <td><Issue r={r} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValueCell({ field, value, det }: { field: string; value: string | number | null | undefined; det?: FieldDetail }) {
  const text = formatValue(field, value);
  if (!text) {
    return <span className="absent">{det ? (det.label_found ? "Blank in the document" : "Not in the document") : "-"}</span>;
  }
  return (
    <>
      <span className="val">{text}</span> {det && <Conf d={det} />}
      {det?.snippet && <div className="snip">{det.snippet}</div>}
    </>
  );
}

function FieldTable({ d, defects }: { d: NonNullable<EmailDetail["detail"]>; defects: string[] }) {
  if (!d.si_fields || !d.bl_fields) return null;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Field</th><th>SI value</th><th>BL value</th><th>Result</th></tr></thead>
          <tbody>
            {FIELDS.map((f) => {
              const si = d.si_detail?.[f], bl = d.bl_detail?.[f];
              const low = (si && si.normalized !== null && si.confidence < 0.6) || (bl && bl.normalized !== null && bl.confidence < 0.6);
              return (
                <tr key={f} className={defects.includes(f) ? "diff" : ""}>
                  <td>{FIELD_LABELS[f]}</td>
                  <td><ValueCell field={f} value={d.si_fields?.[f]} det={si} /></td>
                  <td><ValueCell field={f} value={d.bl_fields?.[f]} det={bl} /></td>
                  <td>
                    {defects.includes(f) ? "MISMATCH" : "match"}
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
        </p>
      )}
    </>
  );
}

function ReviewForm({ item, onSaved }: { item: EmailDetail; onSaved: () => void }) {
  const prior = item.human_decision;
  const [status, setStatus] = useState(prior?.status ?? (item.status === "MISMATCH" ? "MISMATCH" : "OK"));
  const [fields, setFields] = useState<string[]>(prior?.defect_fields ?? item.defect_fields);
  const [note, setNote] = useState(prior?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const toggle = (f: string) => setFields((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  async function save() {
    setBusy(true); setMsg("");
    try {
      await submitReview(item.email_id, { status, defect_fields: status === "MISMATCH" ? fields : [], note });
      setMsg("Saved. The report now uses your decision.");
      onSaved();
    } catch (e) {
      setMsg(`Could not save: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }

  async function retry() {
    setBusy(true); setMsg("");
    try { await retryEmail(item.email_id); setMsg("Retry queued. Refresh the list in a moment."); }
    catch (e) { setMsg(`Could not retry: ${(e as Error).message}`); }
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
        <button disabled={busy} onClick={save}>Save decision</button>
        <button className="secondary" disabled={busy} onClick={retry}>Retry processing</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
    </div>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [item, setItem] = useState<EmailDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    getEmail(id).then(setItem).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => { setItem(null); load(); }, [load]);

  if (error) return <div className="panel"><div className="alert bad">Could not load {id}: {error}</div></div>;
  if (!item) return <div className="panel muted">Loading {id}...</div>;

  const isComparison = item.category === "BL_COMPARISON";
  return (
    <div className="panel">
      <h3>{item.title || item.subject}</h3>
      <div className="meta">
        {item.email_id} · from {item.email.from} · {item.category} / {item.intent ?? "-"} · <Pill status={item.status} />
        <br />Original subject: {item.email.subject}
      </div>
      {item.human_decision && <div className="alert ok">A person set this result to {item.human_decision.status}.</div>}
      {item.review_reason && !item.human_decision && (
        <div className="alert warn"><b>Needs a human decision:</b> {REASON_TEXT[item.review_reason] ?? item.review_reason} ({item.review_reason})</div>
      )}
      {item.detail_error && <div className="alert bad">Could not load the SI/BL fields: {item.detail_error}</div>}
      {isComparison && item.detail && item.detail.si_fields && item.detail.bl_fields && (
        <>
          {item.status === "MISMATCH"
            ? <div className="alert bad">SI and BL differ on: {item.defect_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</div>
            : item.status === "OK" && <div className="alert ok">No mismatch detected.</div>}
          <FieldTable d={item.detail} defects={item.defect_fields} />
        </>
      )}
      {isComparison && item.detail && (item.detail.si_text || item.detail.bl_text) && (
        <details open={item.status === "NEEDS_REVIEW"}>
          <summary>Source documents</summary>
          <div className="two">
            <div><div className="meta">SI text</div><pre>{item.detail.si_text ?? "not available"}</pre></div>
            <div><div className="meta">BL text</div><pre>{item.detail.bl_text ?? "not available"}</pre></div>
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
        />
      )}
    </div>
  );
}

/** "Process new emails": starts a background run on the server and shows its progress. */
function RunControl({ onDone }: { onDone: () => void }) {
  const [run, setRun] = useState<RunStatus | null>(null);
  const [msg, setMsg] = useState("");
  const running = run?.state === "running";

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      getRun().then((r) => {
        setRun(r);
        if (r.state !== "running") {
          setMsg(r.failed.length ? `Finished. ${r.failed.length} email(s) failed and can be retried.` : `Finished. Processed ${r.done} email(s).`);
          onDone();
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [running, onDone]);

  async function start() {
    setMsg("");
    try {
      const { queued } = await startRun();
      if (!queued) { setMsg("Nothing new: every email in the inbox has already been processed."); return; }
      setRun({ state: "running", done: 0, total: queued, failed: [] });
    } catch (e) { setMsg(`Could not start: ${(e as Error).message}`); }
  }

  return (
    <div className="row">
      <button className="secondary" disabled={running} onClick={start}>{running ? "Processing..." : "Process new emails"}</button>
      {running && run && (
        <span className="progress" title={`${run.done} of ${run.total}`}>
          <span style={{ width: `${run.total ? (100 * run.done) / run.total : 0}%` }} />
        </span>
      )}
      {msg && <span className="muted small">{msg}</span>}
    </div>
  );
}

/** Discrepancy report: every comparison that is a mismatch, needs a person, or was decided by one. CSV opens in Excel. */
function downloadReport(rows: EmailRow[]) {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = ["email_id", "title", "status", "review_reason", "mismatched_fields", "person_decision", "person_note"];
  const lines = rows
    .filter((r) => r.category === "BL_COMPARISON" && (r.status !== "OK" || r.human_decision))
    .map((r) => [
      r.email_id, r.title ?? r.subject, r.status, r.review_reason ?? "",
      r.defect_fields.map((f) => FIELD_LABELS[f] ?? f).join("; "),
      r.human_decision?.status ?? "", r.human_decision?.note ?? "",
    ].map(esc).join(","));
  const blob = new Blob(["﻿" + [head.join(","), ...lines].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "discrepancy-report.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function Home() {
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [online, setOnline] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [waited, setWaited] = useState(0);
  const [category, setCategory] = useState("");
  const [intent, setIntent] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getEmails();
      setRows(res.emails); setOnline(true); setLoaded(true);
    } catch { setOnline(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  // While the backend is down (or waking up on free hosting), keep retrying so the page recovers on its own.
  useEffect(() => {
    if (online) { setWaited(0); return; }
    const t = setInterval(() => { setWaited((w) => w + 4); getHealth().then(() => refresh()).catch(() => {}); }, 4000);
    return () => clearInterval(t);
  }, [online, refresh]);

  // On narrow screens the detail panel sits below the list, so bring it into view when an email is picked.
  const pick = useCallback((id: string) => {
    setSelected(id);
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1000px)").matches) {
      setTimeout(() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  }, []);

  const intents = useMemo(() => [...new Set(rows.map((r) => r.intent).filter(Boolean))].sort() as string[], [rows]);
  const filtered = useMemo(() => rows.filter((r) =>
    (!category || r.category === category) && (!intent || r.intent === intent) && (!status || r.status === status) &&
    (!q || `${r.email_id} ${r.title ?? ""} ${r.subject}`.toLowerCase().includes(q.toLowerCase()))), [rows, category, intent, status, q]);
  const inbox = filtered.filter((r) => r.category !== "SPAM");
  const spam = filtered.filter((r) => r.category === "SPAM");

  const comparisons = rows.filter((r) => r.category === "BL_COMPARISON");
  const tiles: { n: number; label: string; tone?: string }[] = [
    { n: rows.length, label: "Emails processed" },
    { n: comparisons.length, label: "SI vs BL comparisons" },
    { n: comparisons.filter((r) => r.status === "OK" && !r.human_decision).length, label: "Verified automatically", tone: "ok" },
    { n: comparisons.filter((r) => r.status === "MISMATCH").length, label: "Mismatches found", tone: "bad" },
    { n: comparisons.filter((r) => r.status === "NEEDS_REVIEW").length, label: "Need a person", tone: "warn" },
    { n: rows.filter((r) => r.human_decision).length, label: "Decided by a person" },
  ];
  const tabCount = (key: string) => (key ? rows.filter((r) => r.status === key).length : rows.length);

  return (
    <main>
      <div className="head">
        <div>
          <h1>Shipping document verification</h1>
          <p className="sub">SI vs draft BL checks, from inbox to discrepancy report.</p>
        </div>
        <span className={`live ${online ? "on" : "off"}`}>{online ? "Backend online" : "Backend offline"}</span>
      </div>

      {!online && (
        <div className="banner" role="status">
          {loaded
            ? "Backend unreachable - showing the last data. Retrying every few seconds..."
            : `Waking the server${waited ? ` (${waited}s)` : ""}. Free hosting sleeps when idle, so the first load can take up to a minute. Retrying automatically...`}
        </div>
      )}

      <div className="tiles">
        {tiles.map((t) => (
          <div className={`tile ${t.tone ?? ""}`} key={t.label}><b>{t.n}</b><span>{t.label}</span></div>
        ))}
      </div>

      <div className="tabs" role="group" aria-label="Filter by status">
        {STATUS_TABS.map((t) => (
          <button key={t.label} className={`tab ${status === t.key ? "active" : ""}`} aria-pressed={status === t.key} onClick={() => setStatus(t.key)}>
            {t.label} <span className="count">{tabCount(t.key)}</span>
          </button>
        ))}
      </div>

      <div className="filters">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={intent} onChange={(e) => setIntent(e.target.value)} aria-label="Intent">
          <option value="">All intents</option>{intents.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </select>
        <input type="text" placeholder="Search title / id" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <button className="secondary" onClick={refresh}>Refresh</button>
        <button className="secondary" onClick={() => downloadReport(rows)} disabled={!rows.length}>Download report (CSV)</button>
        <RunControl onDone={refresh} />
      </div>

      <div className="layout">
        <div className="list-col">
          <h2>Inbox ({inbox.length})</h2>
          <EmailTable rows={inbox} selected={selected} onPick={pick} maxHeight="68vh"
            empty={loaded ? "No emails match the filters." : "Loading..."} />

          <details className="spam">
            <summary>Spam ({spam.length})</summary>
            <EmailTable rows={spam} selected={selected} onPick={pick} maxHeight="30vh" empty="No spam matches the filters." />
          </details>
        </div>

        <aside className="detail-col" ref={panelRef}>
          {selected
            ? <Detail id={selected} onChanged={refresh} />
            : <div className="panel placeholder"><b>Pick an email</b><br />Its SI and BL fields, confidence and source lines will appear here.</div>}
        </aside>
      </div>
    </main>
  );
}
