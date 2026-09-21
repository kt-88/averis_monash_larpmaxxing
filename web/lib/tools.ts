// Client for the email simulator (compose an email) and "re-run with Gemini" endpoints.
import { API } from "@/lib/api";

export type SimInfo = {
  enabled: boolean; allowed: string[]; max_attachments: number; max_file_mb: number; max_per_hour: number; stored: number;
};
export type SimAttachment = { filename: string; content_base64: string };
export type SimEmailInput = { from: string; subject: string; body: string; attachments: SimAttachment[] };
export type SimEntry = {
  category: string; intent: string | null; title: string | null; status: string;
  review_reason: string | null; defect_fields: string[];
};
export type SecondOpinion = { checked: number; agree: number; disagreements: RerunDisagreement[] };
export type SimStatus = {
  email_id: string; state: "processing" | "done" | "failed"; error?: string; entry?: SimEntry;
  second_opinion?: SecondOpinion | null;   // Gemini's own reading of the SI and BL, when it was asked
};

export type RerunChange = { what: string; before: unknown; after: unknown };
export type RerunFieldChange = { side: "si" | "bl"; field: string; before: unknown; after: unknown };
export type RerunDisagreement = { side: "si" | "bl"; field: string; system: unknown; gemini: unknown };
export type RerunResult = {
  email_id: string; gemini_calls: number; category: string; status: string; changed: boolean;
  changes: RerunChange[]; field_changes: RerunFieldChange[];
  agreement: { checked: number; agree: number; disagreements: RerunDisagreement[] };
};

/** Turn the server's error body into one readable sentence (FastAPI sends {"detail": "..."} or a list of problems). */
async function failure(res: Response): Promise<Error> {
  let text = "";
  try {
    const body = await res.json();
    const d = body?.detail;
    text = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).filter(Boolean).join("; ") : "";
  } catch { /* not JSON */ }
  return new Error(text || `The server answered ${res.status}`);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(`${API}${path}`, { ...init, cache: "no-store" }); }
  catch { throw new Error("Could not reach the server. It may be waking up: try again in a few seconds."); }
  if (!res.ok) throw await failure(res);
  return res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const getSimInfo = () => call<SimInfo>("/simulate/info");
export const sendSimEmail = (email: SimEmailInput) => call<{ email_id: string }>("/simulate/emails", json(email));
export const getSimStatus = (id: string) => call<SimStatus>(`/simulate/emails/${id}`);
export const deleteSimEmail = (id: string) => call<{ deleted: string }>(`/simulate/emails/${id}`, { method: "DELETE" });
export const rerunEmail = (id: string) => call<RerunResult>(`/emails/${id}/rerun`, { method: "POST" });

export const isSimulated = (emailId: string) => emailId.startsWith("sim_");

// ---- files and text -> base64 (the API takes JSON, so attachments travel as base64) ----
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
export const textToBase64 = (text: string) => bytesToBase64(new TextEncoder().encode(text));
export async function fileToBase64(file: File): Promise<string> {
  return bytesToBase64(new Uint8Array(await file.arrayBuffer()));
}
