export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const FIELDS = [
  "shipper", "consignee", "notify_party", "port_of_loading",
  "port_of_discharge", "container_count", "gross_weight_kg",
] as const;

export const FIELD_LABELS: Record<string, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight (kg)",
};

export const CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"];

export type HumanDecision = {
  status: string; defect_fields: string[]; note: string;
  reason?: string | null; accepted_blanks?: string[];
};

// Why a reviewer decided as they did. Only blank_acceptable teaches the system anything.
export const DECISION_REASONS: Record<string, string> = {
  blank_acceptable: "Blank on the SI is fine - the BL has it",
  system_wrong: "The system misjudged this",
  genuine_issue: "The flagged problem is real",
  other: "Other",
};


export type EmailRow = {
  email_id: string;
  category: string;
  intent: string | null;
  title: string | null;
  subject: string;
  status: string;
  review_reason: string | null;
  defect_fields: string[];
  has_defect: boolean;
  human_decision: HumanDecision | null;
  learned_rule?: string[];   // fields a learned reviewer rule excused, so no person was needed
};

// What the extractor knows about one field: the value as written, the comparable value, how sure it is
// (0-1, computed from real checks), the source line it came from, and whether the label exists at all.
export type FieldDetail = {
  value: string | number | null;
  normalized: string | number | null;
  confidence: number;
  snippet: string | null;
  label_found: boolean;
  llm?: string | number | null;   // what Gemini read, when it was asked (re-run with Gemini)
  agree?: boolean | null;
};

export type EmailDetail = EmailRow & {
  email: { subject: string; from: string; body: string; attachments: string[] };
  detail: {
    si_fields: Record<string, string | number | null> | null;
    bl_fields: Record<string, string | number | null> | null;
    si_detail?: Record<string, FieldDetail> | null;
    bl_detail?: Record<string, FieldDetail> | null;
    si_text: string | null;
    bl_text: string | null;
    learned_exceptions?: string[];
  } | null;
  detail_error?: string;
};

export type RunStatus = {
  state: "idle" | "running" | "finished";
  done: number;
  total: number;
  failed: { email_id: string; error: string }[];
};

/** Human-friendly value: 131322 -> "131,322 kg", 6 -> "6 containers". Empty string when there is no value. */
export function formatValue(field: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (field === "gross_weight_kg" && typeof v === "number") return `${v.toLocaleString("en-US")} kg`;
  if (field === "container_count" && typeof v === "number") return `${v} container${v === 1 ? "" : "s"}`;
  return String(v);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const getHealth = () => request<{ ok: boolean; emails_processed: number }>("/health");
export const getEmails = () => request<{ count: number; emails: EmailRow[] }>("/emails");
export const getEmail = (id: string) => request<EmailDetail>(`/emails/${id}`);
export const getRun = () => request<RunStatus>("/runs/current");
export const startRun = () => request<{ queued: number }>("/runs?only_missing=true", { method: "POST" });
export const retryEmail = (id: string) => request<{ queued: number }>(`/emails/${id}/retry`, { method: "POST" });
export const submitReview =(id: string, body: HumanDecision) =>
  request<EmailRow>(`/emails/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
