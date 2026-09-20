import { EmailRow, FIELD_LABELS } from "@/lib/api";

/** Discrepancy report: every comparison that is a mismatch, needs a person, or was decided by one. CSV opens in Excel. */
export function downloadReport(rows: EmailRow[]): number {
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
  return lines.length;
}
