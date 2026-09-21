"use client";

import { useState } from "react";
import { FIELD_LABELS, formatValue } from "@/lib/api";
import { RerunResult, deleteSimEmail, isSimulated, rerunEmail } from "@/lib/tools";
import { useToast } from "@/components/ui";

const CLASSIFICATION = ["category", "intent", "title"];
const show = (field: string, v: unknown) => formatValue(field, v) || "blank";

function Verdict({ r }: { r: RerunResult }) {
  const off = r.agreement.disagreements.length;
  const same = r.changes.filter((c) => CLASSIFICATION.includes(c.what)).length === 0;
  const status = r.changes.find((c) => c.what === "status");
  const tone = off ? "warn" : r.changed ? "warn" : "ok";
  const headline = off
    ? `Gemini read ${off} value${off === 1 ? "" : "s"} differently from the rules`
    : r.changed ? "Gemini's fresh answer changed something"
    : "Gemini gives the same answer";
  return (
    <div className={`rerun-result alert ${tone}`} role="status" aria-live="polite">
      <b>{headline}</b>
      <ul>
        <li>{same
          ? "Classification: the same."
          : <>Classification changed: {r.changes.filter((c) => CLASSIFICATION.includes(c.what))
              .map((c) => `${c.what} ${String(c.before ?? "-")} → ${String(c.after ?? "-")}`).join("; ")}.</>}</li>
        <li>{status ? <>Result changed: {String(status.before)} → {String(status.after)}.</> : <>Result: {r.status.replace("_", " ").toLowerCase()} (unchanged).</>}</li>
        {r.category === "BL_COMPARISON" && (
          <li>{r.agreement.checked
            ? <>Second opinion on the fields: Gemini read the SI and the BL separately and matched {r.agreement.agree} of {r.agreement.checked} values.</>
            : <>The fields were not cross-checked (the documents could not be compared).</>}</li>
        )}
        {r.field_changes.map((c) => (
          <li key={c.side + c.field}>{c.side.toUpperCase()} {FIELD_LABELS[c.field] ?? c.field}: {show(c.field, c.before)} → {show(c.field, c.after)}</li>
        ))}
      </ul>
      {off > 0 && (
        <table className="rerun-table">
          <thead><tr><th>Field</th><th>Rules read</th><th>Gemini read</th></tr></thead>
          <tbody>
            {r.agreement.disagreements.map((d) => (
              <tr key={d.side + d.field}>
                <td>{d.side.toUpperCase()} · {FIELD_LABELS[d.field] ?? d.field}</td>
                <td>{show(d.field, d.system)}</td><td>{show(d.field, d.gemini)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="muted small" style={{ marginTop: 6 }}>
        The values from the document itself were kept. A person&apos;s decision, if there is one, was not touched.
        {r.gemini_calls > 0 && <> Used {r.gemini_calls} Gemini call{r.gemini_calls === 1 ? "" : "s"}.</>}
      </div>
    </div>
  );
}

/** Ask Gemini again about this email (ignoring its saved answers), and show what it says. */
export function RerunPanel({ id, onDone, onDeleted }: { id: string; onDone: () => void; onDeleted: () => void }) {
  const toast = useToast();
  const [stage, setStage] = useState<"idle" | "confirm" | "running">("idle");
  const [result, setResult] = useState<RerunResult | null>(null);
  const [error, setError] = useState("");
  const simulated = isSimulated(id);

  async function run() {
    setStage("running"); setError(""); setResult(null);
    try {
      const r = await rerunEmail(id);
      setResult(r);
      onDone();
    } catch (e) { setError((e as Error).message); }
    finally { setStage("idle"); }
  }

  async function remove() {
    if (!window.confirm(`Delete the test email ${id}? This also removes its result and any decision about it.`)) return;
    try { await deleteSimEmail(id); toast("Test email deleted.", "ok"); onDeleted(); }
    catch (e) { toast(`Could not delete: ${(e as Error).message}`, "bad"); }
  }

  return (
    <div className="rerun">
      <div className="rerun-bar">
        {stage === "idle" && (
          <>
            <span className="muted small">Not sure about this result? Ask Gemini to check it again.</span>
            <div className="row">
              {simulated && <><span className="chip learned">Simulated test email</span><button className="secondary" onClick={remove}>Delete</button></>}
              <button className="secondary" onClick={() => setStage("confirm")}>Re-run with Gemini</button>
            </div>
          </>
        )}
        {stage === "confirm" && (
          <>
            <span className="small">This asks Gemini again, ignoring its saved answers: about 1 to 3 calls and 10 to 20 seconds.</span>
            <div className="row"><button onClick={run}>Ask Gemini again</button><button className="secondary" onClick={() => setStage("idle")}>Cancel</button></div>
          </>
        )}
        {stage === "running" && <span className="small" role="status" aria-live="polite"><i className="spinner" aria-hidden="true" /> Gemini is reading this email again...</span>}
      </div>
      {error && <div className="alert bad" role="alert">{error}</div>}
      {result && <Verdict r={result} />}
    </div>
  );
}
