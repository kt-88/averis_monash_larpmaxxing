"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CATEGORIES, EmailDetail, EmailRow, FIELDS, FIELD_LABELS, STATUSES,
  getEmail, getEmails, getHealth, retryEmail, submitReview,
} from "@/lib/api";

const REASON_TEXT: Record<string, string> = {
  missing_attachment: "The SI and/or the BL was not attached.",
  wrong_doc_type: "The second attachment is not a Bill of Lading.",
  unreadable: "An attachment could not be read (scanned, empty or corrupt).",
  missing_value: "A required field is blank in a source document.",
};

function Pill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{status.replace("_", " ")}</span>;
}

function EmailTable({ rows, selected, onPick, empty }: {
  rows: EmailRow[]; selected: string | null; onPick: (id: string) => void; empty: string;
}) {
  if (!rows.length) return <div className="table-wrap"><div className="empty">{empty}</div></div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>ID</th><th>Title</th><th>Category</th><th>Intent</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.email_id} className={selected === r.email_id ? "sel" : ""} onClick={() => onPick(r.email_id)}>
              <td>{r.email_id}</td>
              <td>{r.title || r.subject}</td>
              <td>{r.category}</td>
              <td className="muted">{r.intent ?? "-"}</td>
              <td><Pill status={r.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FieldTable({ d, defects }: { d: NonNullable<EmailDetail["detail"]>; defects: string[] }) {
  if (!d.si_fields || !d.bl_fields) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Field</th><th>SI value</th><th>BL value</th><th>Result</th></tr></thead>
        <tbody>
          {FIELDS.map((f) => (
            <tr key={f} className={defects.includes(f) ? "diff" : ""}>
              <td>{FIELD_LABELS[f]}</td>
              <td>{String(d.si_fields?.[f] ?? "-")}</td>
              <td>{String(d.bl_fields?.[f] ?? "-")}</td>
              <td>{defects.includes(f) ? "MISMATCH" : "match"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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

export default function Home() {
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [online, setOnline] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [category, setCategory] = useState("");
  const [intent, setIntent] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getEmails();
      setRows(res.emails); setOnline(true); setLoaded(true);
    } catch { setOnline(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  // While the backend is down, keep retrying so the page recovers on its own.
  useEffect(() => {
    if (online) return;
    const t = setInterval(() => getHealth().then(() => refresh()).catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [online, refresh]);

  const intents = useMemo(() => [...new Set(rows.map((r) => r.intent).filter(Boolean))].sort() as string[], [rows]);
  const filtered = useMemo(() => rows.filter((r) =>
    (!category || r.category === category) && (!intent || r.intent === intent) && (!status || r.status === status) &&
    (!q || `${r.email_id} ${r.title ?? ""} ${r.subject}`.toLowerCase().includes(q.toLowerCase()))), [rows, category, intent, status, q]);
  const inbox = filtered.filter((r) => r.category !== "SPAM");
  const spam = filtered.filter((r) => r.category === "SPAM");
  const count = (fn: (r: EmailRow) => boolean) => rows.filter(fn).length;

  return (
    <main>
      <h1>Shipping document verification</h1>
      <p className="sub">SI vs draft BL checks, from inbox to discrepancy report.</p>

      {!online && (
        <div className="banner">
          {loaded
            ? "Backend unreachable - showing the last data. Retrying every few seconds..."
            : "Waiting for the backend to respond. Retrying every few seconds..."}
        </div>
      )}

      <div className="tiles">
        <div className="tile"><b>{rows.length}</b><span>Emails processed</span></div>
        {CATEGORIES.map((c) => <div className="tile" key={c}><b>{count((r) => r.category === c)}</b><span>{c}</span></div>)}
        {STATUSES.map((s) => <div className="tile" key={s}><b>{count((r) => r.status === s)}</b><span>{s.replace("_", " ")}</span></div>)}
      </div>

      <div className="filters">
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={intent} onChange={(e) => setIntent(e.target.value)}>
          <option value="">All intents</option>{intents.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <input type="text" placeholder="Search title / id" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="secondary" onClick={refresh}>Refresh</button>
      </div>

      <h2>Inbox ({inbox.length})</h2>
      <EmailTable rows={inbox} selected={selected} onPick={setSelected} empty={loaded ? "No emails match the filters." : "Loading..."} />

      <h2>Spam ({spam.length})</h2>
      <EmailTable rows={spam} selected={selected} onPick={setSelected} empty="No spam matches the filters." />

      {selected && <Detail id={selected} onChanged={refresh} />}
    </main>
  );
}
