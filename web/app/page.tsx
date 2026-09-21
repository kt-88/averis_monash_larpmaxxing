"use client";
//for displaying content in vercel
import {
  CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent,
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { API, CATEGORIES, EmailRow, getEmails, getHealth } from "@/lib/api";
import { Compose } from "@/components/Compose";
import { Detail } from "@/components/Detail";
import { EmailTable } from "@/components/EmailTable";
import { RunControl } from "@/components/RunControl";
import { Summary } from "@/components/Summary";
import { Logo, ToastProvider, useToast } from "@/components/ui";
import { downloadReport } from "@/lib/report";
import { SimInfo, getSimInfo, isSimulated } from "@/lib/tools";

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "MISMATCH", label: "Mismatch" },
  { key: "NEEDS_REVIEW", label: "Needs review" },
  { key: "OK", label: "OK" },
];

const DEFAULT_SHARE = 5 / 12;   // list : details = 5 : 7 until the user drags the divider
const MIN_SHARE = 0.2, MAX_SHARE = 0.8;
const clampShare = (v: number) => Math.min(MAX_SHARE, Math.max(MIN_SHARE, v));

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
  const [view, setView] = useState<"inbox" | "spam" | "summary">("inbox");   // which page the sidebar has open
  const [ready, setReady] = useState(false);      // true once filters were read from the address bar
  const [filtersOpen, setFiltersOpen] = useState(false);   // the category / intent dropdowns are tucked away by default
  const [sideOpen, setSideOpen] = useState(true);        // sidebar expanded, or collapsed to icons
  const [listShare, setListShare] = useState(DEFAULT_SHARE); // share of the width the email list takes
  const [composeOpen, setComposeOpen] = useState(false);       // the "new email" window (email simulator)
  const [sim, setSim] = useState<SimInfo | null>(null);         // null until the backend says the simulator is on
  const layoutRef = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    if (online) getSimInfo().then((i) => setSim(i.enabled ? i : null)).catch(() => setSim(null));
  }, [online]);
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
    const v = p.get("view"); if (v === "spam" || v === "summary") setView(v);
    try {
      const m = Number(localStorage.getItem("minutesPerCheck")); if (m > 0) setMinutes(m);
      if (localStorage.getItem("sideOpen") === "0") setSideOpen(false);
      if (localStorage.getItem("filtersOpen") === "1") setFiltersOpen(true);
      const w = Number(localStorage.getItem("listShare")); if (w >= MIN_SHARE && w <= MAX_SHARE) setListShare(w);
    } catch { /* storage blocked */ }
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
    if (view !== "inbox") p.set("view", view);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [ready, category, intent, status, q, selected, view]);

  const remember = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* storage blocked */ } };
  const toggleSide = () => setSideOpen((open) => { remember("sideOpen", open ? "0" : "1"); return !open; });
  const toggleFilters = () => setFiltersOpen((open) => { remember("filtersOpen", open ? "0" : "1"); return !open; });
  const activeFilters = (category ? 1 : 0) + (intent ? 1 : 0);   // status is already shown by the tabs above
  const commitShare = (v: number) => { setListShare(v); remember("listShare", String(v)); };

  // Drag the divider between the list and the details. The CSS variable is set directly while dragging (no
  // re-render of 500 rows per pixel) and saved once when the pointer is released.
  const startDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    const box = layoutRef.current;
    if (!box) return;
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const rect = box.getBoundingClientRect();
    let share = listShare;
    box.classList.add("dragging");
    const move = (ev: PointerEvent) => {
      share = clampShare((ev.clientX - rect.left - 7) / (rect.width - 14));   // 7 = half the divider's width
      box.style.setProperty("--list-share", String(share));
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      box.classList.remove("dragging");
      commitShare(share);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };
  const onDividerKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); commitShare(clampShare(listShare - 0.02)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); commitShare(clampShare(listShare + 0.02)); }
    else if (e.key === "Home") { e.preventDefault(); commitShare(DEFAULT_SHARE); }
  };

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
  const visible = view === "spam" ? spam : view === "summary" ? [] : inbox;
  const total = (spamView: boolean) => rows.filter((r) => (r.category === "SPAM") === spamView).length;
  const tabCount = (key: string) => (key ? rows.filter((r) => r.status === key).length : rows.length);

  // The review queue: comparisons the system would not decide alone and nobody has decided yet.
  // Emails composed in the simulator stay visible in the inbox, but are not counted in the numbers, the queue or the report.
  const real = useMemo(() => rows.filter((r) => !isSimulated(r.email_id)), [rows]);
  const pending = useMemo(
    () => real.filter((r) => r.category === "BL_COMPARISON" && r.review_reason && !r.human_decision), [real]);

  const startReview = () => {
    setCategory(""); setIntent(""); setQ(""); setStatus("NEEDS_REVIEW"); setView("inbox");
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
      if (e.metaKey || e.ctrlKey || e.altKey || composeOpen) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement).tagName)) return;
      if (e.key === "c" && sim) { e.preventDefault(); setComposeOpen(true); }
      else if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "Escape") setSelected(null);
      else if (e.key === "j" || e.key === "k") {
        const i = visible.findIndex((r) => r.email_id === selected);
        const next = visible[e.key === "j" ? Math.min(i + 1, visible.length - 1) : Math.max(i - 1, 0)];
        if (next) pick(next.email_id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selected, pick, composeOpen, sim]);

  return (
    <div className={`shell ${sideOpen ? "" : "collapsed"}`}>
      <nav className="side" aria-label="Mailbox views">
        <div className="side-head">
          <div className="side-label">Mailbox</div>
          <button className="side-toggle" aria-expanded={sideOpen} aria-label={sideOpen ? "Collapse sidebar" : "Expand sidebar"}
            title={sideOpen ? "Collapse sidebar" : "Expand sidebar"} onClick={toggleSide}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {sideOpen ? <path d="m15 6-6 6 6 6" /> : <path d="m9 6 6 6-6 6" />}
            </svg>
          </button>
        </div>
        <button className={`nav-item ${view === "inbox" ? "active" : ""}`} aria-current={view === "inbox" ? "page" : undefined} title="Inbox" onClick={() => setView("inbox")}>
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z" /></svg>
          <span className="nav-text">Inbox</span><span className="count">{total(false)}</span>
        </button>
        <button className={`nav-item ${view === "spam" ? "active" : ""}`} aria-current={view === "spam" ? "page" : undefined} title="Spam" onClick={() => setView("spam")}>
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 2 3 6v6c0 5 3.8 9.3 9 10 5.2-.7 9-5 9-10V6z" /><path d="M12 8v4M12 16h.01" /></svg>
          <span className="nav-text">Spam</span><span className="count">{total(true)}</span>
        </button>
        <div className="side-divider" role="presentation" />
        <div className="side-label sub-label">Overview</div>
        <button className={`nav-item ${view === "summary" ? "active" : ""}`} aria-current={view === "summary" ? "page" : undefined} title="Summary" onClick={() => setView("summary")}>
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>
          <span className="nav-text">Summary</span>
        </button>
      </nav>
    <main>
      <div className="head">
        <div className="brand">
          <Logo />
          <div>
            <h1>Shipping document verification</h1>
            <p className="sub">SI vs draft BL checks, from inbox to discrepancy report.</p>
          </div>
        </div>
        <div className="head-actions">
          {sim && (
            <button className="compose-btn" onClick={() => setComposeOpen(true)} title="Simulate an email arriving in the inbox (c)">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
              Compose
            </button>
          )}
          <span className={`live ${online ? "on" : "off"}`}>{online ? "Backend online" : "Backend offline"}</span>
        </div>
      </div>

      {!online && (
        <div className="banner" role="status">
          {loaded
            ? "Backend unreachable - showing the last data. Retrying every few seconds..."
            : `Waking the server${waited ? ` (${waited}s)` : ""}. Free hosting sleeps when idle, so the first load can take up to a minute. Retrying automatically...`}
        </div>
      )}

      {view === "summary" ? (
        <section className="zone zone-summary" aria-label="Summary">
          <Summary rows={real} simulated={rows.length - real.length} loaded={loaded} minutes={minutes} onMinutes={changeMinutes} onStartReview={startReview} />
        </section>
      ) : (
      <section className="zone zone-inbox" aria-label={view === "spam" ? "Spam" : "Inbox"}>
      <div className="tabs" role="group" aria-label="Filter by status">
        {STATUS_TABS.map((t) => (
          <button key={t.label} className={`tab ${status === t.key ? "active" : ""}`} aria-pressed={status === t.key} onClick={() => setStatus(t.key)}>
            {t.label} <span className="count">{tabCount(t.key)}</span>
          </button>
        ))}
      </div>

      <div className="filters">
        <button className={`secondary filter-toggle ${filtersOpen ? "open" : ""}`} aria-expanded={filtersOpen} aria-controls="filter-panel" onClick={toggleFilters}>
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8v6l-4 2v-8z" /></svg>
          Filters
          {activeFilters > 0 && <span className="badge" aria-label={`${activeFilters} active`}>{activeFilters}</span>}
          <svg className="chev" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <input ref={searchRef} type="text" placeholder="Search title / id  ( / )" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <button className="secondary" onClick={refresh}>Refresh</button>
        <button className="secondary" disabled={!rows.length}
          onClick={() => toast(`Report downloaded: ${downloadReport(real)} comparisons that need attention.`, "ok")}>
          Download report (CSV)
        </button>
        <RunControl onDone={refresh} />
      </div>
      {filtersOpen && (
        <div id="filter-panel" className="filter-panel">
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
            <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select value={intent} onChange={(e) => setIntent(e.target.value)} aria-label="Intent">
            <option value="">All intents</option>{intents.map((i) => <option key={i}>{i}</option>)}
          </select>
          <button className="secondary" disabled={!activeFilters} onClick={() => { setCategory(""); setIntent(""); }}>Clear filters</button>
        </div>
      )}
      <p className="hint">Shortcuts: {sim && <><kbd>c</kbd> new email · </>}<kbd>/</kbd> search · <kbd>j</kbd> <kbd>k</kbd> next / previous email · <kbd>Esc</kbd> close</p>

      <div className="layout" ref={layoutRef} style={{ "--list-share": listShare } as CSSProperties}>
        <div className="list-col">
          <h2>{view === "spam" ? "Spam" : "Inbox"} ({visible.length})</h2>
          <EmailTable rows={visible} selected={selected} onPick={pick} maxHeight="68vh" loading={!loaded && online}
            empty={loaded ? "No emails match the filters." : "Loading..."} />
        </div>

        <div className="divider" role="separator" aria-orientation="vertical" aria-label="Resize the list and the details"
          aria-valuemin={Math.round(MIN_SHARE * 100)} aria-valuemax={Math.round(MAX_SHARE * 100)} aria-valuenow={Math.round(listShare * 100)}
          tabIndex={0} title="Drag to resize, double-click to reset" onPointerDown={startDrag} onKeyDown={onDividerKey}
          onDoubleClick={() => commitShare(DEFAULT_SHARE)} />

        <aside className="detail-col" ref={panelRef}>
          {selected
            ? <Detail key={selected} id={selected} onChanged={refresh} onClose={() => setSelected(null)} onNext={pending.length ? goNext : undefined} />
            : <div className="panel placeholder"><b>Pick an email</b><br />Its SI and BL fields and the source lines they were read from will appear here.</div>}
        </aside>
      </div>
      </section>
      )}

      {composeOpen && sim && (
        <Compose info={sim} onClose={() => setComposeOpen(false)} onChanged={refresh}
          onOpenEmail={(id) => { setView("inbox"); setCategory(""); setIntent(""); setQ(""); setStatus(""); pick(id); }} />
      )}

      <footer className="foot">
        <span>Next.js on Vercel · FastAPI on Render · Postgres on Neon · Gemini reads the messy documents</span>
        <a href={`${API}/docs`} target="_blank" rel="noreferrer">API docs</a>
      </footer>
    </main>
    </div>
  );
}

export default function Page() {
  return <ToastProvider><Home /></ToastProvider>;
}
