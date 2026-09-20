"use client";

import { KeyboardEvent, useEffect } from "react";
import { EmailRow, FIELD_LABELS } from "@/lib/api";
import { Pill } from "@/components/ui";

/** What was wrong with this email, at a glance: the mismatched fields, or the reason it needs a person. */
function Issue({ r }: { r: EmailRow }) {
  return (
    <>
      {r.status === "MISMATCH" && r.defect_fields.map((f) => <span key={f} className="chip bad">{FIELD_LABELS[f] ?? f}</span>)}
      {r.status === "NEEDS_REVIEW" && <span className="chip warn">{(r.review_reason ?? "review").replace(/_/g, " ")}</span>}
      {r.human_decision && <span className="chip">person decided</span>}
      {!!r.learned_rule?.length && (
        <span className="chip learned" title={`No review needed: reviewers taught the system that a blank SI ${r.learned_rule.map((f) => FIELD_LABELS[f] ?? f).join(", ")} is fine when the BL has it`}>
          learned rule
        </span>
      )}
      {r.status === "OK" && !r.human_decision && !r.learned_rule?.length && <span className="muted">-</span>}
    </>
  );
}

export function EmailTable({ rows, selected, onPick, empty, maxHeight, loading }: {
  rows: EmailRow[]; selected: string | null; onPick: (id: string) => void; empty: string; maxHeight: string; loading?: boolean;
}) {
  // Keep the selected row visible when it changes through j/k, "Save and next" or a shared link.
  useEffect(() => {
    if (selected) document.getElementById(`row-${selected}`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  if (loading) {
    return (
      <div className="table-wrap" aria-busy="true">
        {Array.from({ length: 7 }, (_, i) => <div className="skeleton-row skeleton" key={i} />)}
      </div>
    );
  }
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
              id={`row-${r.email_id}`}
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
