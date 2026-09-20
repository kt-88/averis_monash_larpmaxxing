"use client";

import { useEffect, useState } from "react";
import { RunStatus, getRun, startRun } from "@/lib/api";
import { useToast } from "@/components/ui";

/** "Process new emails": starts a background run on the server and shows its progress. */
export function RunControl({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [run, setRun] = useState<RunStatus | null>(null);
  const running = run?.state === "running";

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      getRun().then((r) => {
        setRun(r);
        if (r.state !== "running") {
          if (r.failed.length) toast(`Finished. ${r.failed.length} email(s) failed and can be retried.`, "bad");
          else toast(`Finished. Processed ${r.done} email(s).`, "ok");
          onDone();
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [running, onDone, toast]);

  async function start() {
    try {
      const { queued } = await startRun();
      if (!queued) { toast("Nothing new: every email in the inbox has already been processed."); return; }
      setRun({ state: "running", done: 0, total: queued, failed: [] });
      toast(`Processing ${queued} new email(s)...`);
    } catch (e) { toast(`Could not start: ${(e as Error).message}`, "bad"); }
  }

  return (
    <div className="row">
      <button className="secondary" disabled={running} onClick={start}>{running ? "Processing..." : "Process new emails"}</button>
      {running && run && (
        <span className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={run.total} aria-valuenow={run.done} title={`${run.done} of ${run.total}`}>
          <span style={{ width: `${run.total ? (100 * run.done) / run.total : 0}%` }} />
        </span>
      )}
    </div>
  );
}
