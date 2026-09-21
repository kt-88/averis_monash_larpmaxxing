"use client";

import type { EmailRow } from "@/lib/api";

/**
 * Headline numbers for the whole inbox.
 * "Resolved automatically" = a comparison that needed no person: it was decided by the rules and no review reason was raised.
 */
export function Summary({ rows, simulated = 0, loaded, minutes, onMinutes, onStartReview }: {
  rows: EmailRow[]; simulated?: number; loaded: boolean; minutes: number; onMinutes: (m: number) => void; onStartReview: () => void;
}) {
  if (!loaded) {
    return (
      <div className="tiles" aria-busy="true">
        {[0, 1, 2, 3].map((i) => <div className="tile skeleton" key={i} style={{ height: 68 }} />)}
      </div>
    );
  }

  const comps = rows.filter((r) => r.category === "BL_COMPARISON");
  const byPerson = comps.filter((r) => r.human_decision);
  const waiting = comps.filter((r) => r.review_reason && !r.human_decision);
  const auto = comps.filter((r) => !r.human_decision && !r.review_reason);
  const okAuto = auto.filter((r) => r.status === "OK").length;
  const mismatchAuto = auto.filter((r) => r.status === "MISMATCH").length;
  const needed = comps.filter((r) => r.review_reason).length;   // cases the system could not decide alone
  const decided = needed - waiting.length;
  const pct = (n: number) => (comps.length ? (100 * n) / comps.length : 0);
  const savedHours = (auto.length * minutes) / 60;

  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{rows.length}</b><span>Emails processed</span></div>
        <div className="tile"><b>{comps.length}</b><span>SI vs BL comparisons</span></div>
        <div className="tile bad"><b>{comps.filter((r) => r.status === "MISMATCH").length}</b><span>Mismatches found</span></div>
        <div className="tile ok">
          <b>{savedHours.toFixed(1)} h</b>
          <span>
            Estimated time saved at{" "}
            <input
              className="mini" type="number" min={0} max={60} value={minutes} aria-label="Minutes per manual check"
              onChange={(e) => onMinutes(Math.max(0, Math.min(60, Number(e.target.value) || 0)))}
            />{" "}
            min per manual check
          </span>
        </div>
      </div>

      <div className="cards">
        <div className="card">
          <div className="card-head"><b>Outcome of {comps.length} comparisons</b><span className="muted small">{Math.round(pct(auto.length))}% resolved without a person</span></div>
          <div className="stack" role="img" aria-label={`${okAuto} verified, ${mismatchAuto} mismatches, ${waiting.length} waiting for a person, ${byPerson.length} decided by a person`}>
            <span className="seg-ok" style={{ width: `${pct(okAuto)}%` }} />
            <span className="seg-bad" style={{ width: `${pct(mismatchAuto)}%` }} />
            <span className="seg-warn" style={{ width: `${pct(waiting.length)}%` }} />
            <span className="seg-person" style={{ width: `${pct(byPerson.length)}%` }} />
          </div>
          <div className="legend-row">
            <span><i className="dot ok" />{okAuto} verified</span>
            <span><i className="dot bad" />{mismatchAuto} mismatches found</span>
            <span><i className="dot warn" />{waiting.length} waiting for a person</span>
            <span><i className="dot person" />{byPerson.length} decided by a person</span>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><b>Review queue</b><span className="muted small">{decided} of {needed} decided</span></div>
          <div className="stack" role="progressbar" aria-valuemin={0} aria-valuemax={needed} aria-valuenow={decided} aria-label="Review progress">
            <span className="seg-ok" style={{ width: `${needed ? (100 * decided) / needed : 0}%` }} />
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <button disabled={!waiting.length} onClick={onStartReview}>{waiting.length ? `Start reviewing (${waiting.length})` : "Queue is empty"}</button>
            <span className="muted small">Cases the system would not guess on: missing, blank or unreadable documents.</span>
          </div>
        </div>
      </div>
      {simulated > 0 && (
        <p className="hint">{simulated} simulated test email{simulated === 1 ? " is" : "s are"} in the inbox but not counted in these numbers.</p>
      )}
    </>
  );
}
