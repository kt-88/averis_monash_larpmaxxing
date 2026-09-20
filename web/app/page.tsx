"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API, CATEGORIES, EmailRow, STATUSES, getEmails, getHealth } from "@/lib/api";
import { Detail } from "@/components/Detail";
import { EmailTable } from "@/components/EmailTable";
import { RunControl } from "@/components/RunControl";
import { Summary } from "@/components/Summary";
import { Logo, ToastProvider, useToast } from "@/components/ui";
import { downloadReport } from "@/lib/report";

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "MISMATCH", label: "Mismatch" },
  { key: "NEEDS_REVIEW", label: "Needs review" },
  { key: "OK", label: "OK" },
];

function Home() {
  const toast = useToast();
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [online, setOnline] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [waited, setWaited] = useState(0);
  const [category, setCategory] = useState("");
  const [intent, setIntent] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [ready, setReady] = useState(false);      // true once filters were read from the address bar
  const [minutes, setMinutes] = useState(3);      // assumption behind "time saved": minutes per manual check
  const panelRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

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

  // Filters and the open email live in the address bar, so a link can be shared or bookmarked.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setCategory(p.get("category") ?? ""); setIntent(p.get("intent") ?? "");
    setStatus(p.get("status") ?? ""); setQ(p.get("q") ?? "");
    const id = p.get("id"); if (id) setSelected(id);
    try { const m = Number(localStorage.getItem("minutesPerCheck")); if (m > 0) setMinutes(m); } catch { /* storage blocked */ }
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    const p = new URLSearchParams();
    if (category) p.set("category", category);
    if (intent) p.set("intent", intent);
    if (status) p.set("status", status);
    if (q) p.set("q", q);
    if (selected) p.set("id", selected);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [ready, category, intent, status, q, selected]);

  const changeMinutes = (m: number) => {
    setMinutes(m);
    try { localStorage.setItem("minutesPerCheck", String(m)); } catch { /* storage blocked */ }
  };

  // On narrow screens the detail panel sits below the list, so bring it into view when an email is picked.
  const pick = useCallback((id: string) => {
    setSelected(id);
    if (window.matchMedia("(max-width: 1000px)").matches) {
      setTimeout(() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  }, []);

  const intents = useMemo(() => [...new Set(rows.map((r) => r.intent).filter(Boolean))].sort() as string[], [rows]);
  const filtered = useMemo(() => rows.filter((r) =>
    (!category || r.category === category) && (!intent || r.intent === intent) && (!status || r.status === status) &&
    (!q || `${r.email_id} ${r.title ?? ""} ${r.subject}`.toLowerCase().includes(q.toLowerCase()))), [rows, category, intent, status, q]);
  const inbox = filtered.filter((r) => r.category !== "SPAM");
  const spam = filtered.filter((r) => r.category === "SPAM");
  const tabCount = (key: string) => (key ? rows.filter((r) => r.status === key).length : rows.length);

  // The review queue: comparisons the system would not decide alone and nobody has decided yet.
  const pending = useMemo(
    () => rows.filter((r) => r.category === "BL_COMPARISON" && r.review_reason && !r.human_decision), [rows]);

  const startReview = () => {
    setCategory(""); setIntent(""); setQ(""); setStatus("NEEDS_REVIEW");
    if (pending[0]) pick(pending[0].email_id);
  };
  const goNext = useCallback(() => {
    const queue = pending.filter((r) => r.email_id !== selected);
    const next = queue.find((r) => selected && r.email_id > selected) ?? queue[0];
    if (next) pick(next.email_id);
    else { setSelected(null); toast("Review queue is empty. Nice work.", "ok"); }
  }, [pending, selected, pick, toast]);

  // Keyboard shortcuts: "/" search, j / k next and previous email, Esc close. Ignored while typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement).tagName)) return;
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "Escape") setSelected(null);
      else if (e.key === "j" || e.key === "k") {
        const i = inbox.findIndex((r) => r.email_id === selected);
        const next = inbox[e.key === "j" ? Math.min(i + 1, inbox.length - 1) : Math.max(i - 1, 0)];
        if (next) pick(next.email_id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inbox, selected, pick]);

  return (
    <main>
      <div className="head">
        <div className="brand">
          <Logo />
          <div>
            <h1>Shipping document verification</h1>
            <p className="sub">SI vs draft BL checks, from inbox to discrepancy report.</p>
          </div>
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

      <Summary rows={rows} loaded={loaded} minutes={minutes} onMinutes={changeMinutes} onStartReview={startReview} />

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
        <input ref={searchRef} type="text" placeholder="Search title / id  ( / )" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <button className="secondary" onClick={refresh}>Refresh</button>
        <button className="secondary" disabled={!rows.length}
          onClick={() => toast(`Report downloaded: ${downloadReport(rows)} comparisons that need attention.`, "ok")}>
          Download report (CSV)
        </button>
        <RunControl onDone={refresh} />
      </div>
      <p className="hint">Shortcuts: <kbd>/</kbd> search · <kbd>j</kbd> <kbd>k</kbd> next / previous email · <kbd>Esc</kbd> close</p>

      <div className="layout">
        <div className="list-col">
          <h2>Inbox ({inbox.length})</h2>
          <EmailTable rows={inbox} selected={selected} onPick={pick} maxHeight="68vh" loading={!loaded && online}
            empty={loaded ? "No emails match the filters." : "Loading..."} />

          <details className="spam">
            <summary>Spam ({spam.length})</summary>
            <EmailTable rows={spam} selected={selected} onPick={pick} maxHeight="30vh" empty="No spam matches the filters." />
          </details>
        </div>

        <aside className="detail-col" ref={panelRef}>
          {selected
            ? <Detail key={selected} id={selected} onChanged={refresh} onClose={() => setSelected(null)} onNext={pending.length ? goNext : undefined} />
            : <div className="panel placeholder"><b>Pick an email</b><br />Its SI and BL fields and the source lines they were read from will appear here.</div>}
        </aside>
      </div>

      <footer className="foot">
        <span>Next.js on Vercel · FastAPI on Render · Postgres on Neon · Gemini reads the messy documents</span>
        <a href={`${API}/docs`} target="_blank" rel="noreferrer">API docs</a>
      </footer>
    </main>
  );
}

export default function Page() {
  return <ToastProvider><Home /></ToastProvider>;
}
