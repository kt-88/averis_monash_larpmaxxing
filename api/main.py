"""FastAPI backend: uvicorn api.main:app --reload   (docs at http://localhost:8000/docs)

Results live in output/submission.json and human decisions in output/review_decisions.json
until step 3 moves them into Postgres.
"""
import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from loader import Inbox  # noqa: E402
from src.cache import BudgetExceeded  # noqa: E402
from src.pipeline import analyze_comparison, process_email, save_submission  # noqa: E402

SUBMISSION_PATH = ROOT / "output" / "submission.json"
DECISIONS_PATH = ROOT / "output" / "review_decisions.json"
SOURCE = os.environ.get("INBOX_SOURCE", "data")

app = FastAPI(title="Shipping document verification API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_run = {"state": "idle", "done": 0, "total": 0, "failed": []}


def get_inbox() -> Inbox:
    return Inbox(SOURCE if SOURCE.startswith("http") or Path(SOURCE).is_absolute() else str(ROOT / SOURCE))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def merged(email_id: str, entry: dict, decisions: dict) -> dict:
    """Entry with the human decision applied on top (if any)."""
    out = {"email_id": email_id, **entry, "human_decision": decisions.get(email_id)}
    if (d := decisions.get(email_id)):
        out["status"] = d["status"]
        out["defect_fields"] = d.get("defect_fields", entry["defect_fields"])
        out["has_defect"] = d["status"] == "MISMATCH"
    return out


@app.get("/health")
def health():
    return {"ok": True, "emails_processed": len(read_json(SUBMISSION_PATH))}


@app.get("/emails")
def list_emails(category: str | None = None, intent: str | None = None, status: str | None = None,
                q: str | None = None):
    inbox, decisions = get_inbox(), read_json(DECISIONS_PATH)
    rows = []
    for email_id, entry in read_json(SUBMISSION_PATH).items():
        row = merged(email_id, entry, decisions)
        row["subject"] = inbox.get(email_id)["subject"]
        if category and row["category"] != category:
            continue
        if intent and row.get("intent") != intent:
            continue
        if status and row["status"] != status:
            continue
        if q and q.lower() not in f"{email_id} {row.get('title') or ''} {row['subject']}".lower():
            continue
        rows.append(row)
    return {"count": len(rows), "emails": rows}


@app.get("/emails/{email_id}")
def get_email(email_id: str):
    entry = read_json(SUBMISSION_PATH).get(email_id)
    if entry is None:
        raise HTTPException(404, f"{email_id} has not been processed")
    inbox = get_inbox()
    email = inbox.get(email_id)
    result = merged(email_id, entry, read_json(DECISIONS_PATH))
    result["email"] = {k: email[k] for k in ("subject", "from", "body", "attachments")}
    result["detail"] = None
    if entry["category"] == "BL_COMPARISON":
        try:
            d = analyze_comparison(inbox, email)
            result["detail"] = {k: v for k, v in d.items() if k != "entry"}
        except Exception as e:  # BudgetExceeded / API failure: keep the page usable
            result["detail_error"] = repr(e)
    return result


class Decision(BaseModel):
    status: str  # OK or MISMATCH
    defect_fields: list[str] = []
    note: str = ""


@app.post("/emails/{email_id}/review")
def submit_review(email_id: str, body: Decision):
    entry = read_json(SUBMISSION_PATH).get(email_id)
    if entry is None:
        raise HTTPException(404, f"{email_id} has not been processed")
    if body.status not in ("OK", "MISMATCH"):
        raise HTTPException(422, "status must be OK or MISMATCH")
    with _lock:
        decisions = read_json(DECISIONS_PATH)
        decisions[email_id] = body.model_dump()
        DECISIONS_PATH.write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    return merged(email_id, entry, decisions)


def process_and_save(email_ids: list[str]) -> None:
    inbox = get_inbox()
    _run.update(state="running", done=0, total=len(email_ids), failed=[])
    for email_id in email_ids:
        try:
            result = process_email(inbox, inbox.get(email_id))["entry"]
            with _lock:
                data = read_json(SUBMISSION_PATH)
                data[email_id] = result
                save_submission(data, str(SUBMISSION_PATH))
        except BudgetExceeded:
            _run["failed"].append({"email_id": email_id, "error": "API budget reached"})
        except Exception as e:
            _run["failed"].append({"email_id": email_id, "error": repr(e)})
        _run["done"] += 1
    _run["state"] = "finished"


@app.post("/runs")
def start_run(background: BackgroundTasks, only_missing: bool = True, limit: int | None = None):
    """Process emails in the background. Poll GET /runs/current for progress."""
    if _run["state"] == "running":
        raise HTTPException(409, "a run is already in progress")
    done = read_json(SUBMISSION_PATH)
    ids = [e["email_id"] for e in get_inbox() if not (only_missing and e["email_id"] in done)]
    ids = ids[:limit] if limit else ids
    _run.update(state="running", done=0, total=len(ids), failed=[])
    background.add_task(process_and_save, ids)
    return {"queued": len(ids)}


@app.get("/runs/current")
def run_status():
    return _run


@app.post("/emails/{email_id}/retry")
def retry_email(email_id: str, background: BackgroundTasks):
    if _run["state"] == "running":
        raise HTTPException(409, "a run is already in progress")
    get_inbox().get(email_id)
    background.add_task(process_and_save, [email_id])
    return {"queued": 1}
