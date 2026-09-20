"""FastAPI backend: python -m uvicorn api.main:app --reload   (docs at http://localhost:8000/docs)

Results and human decisions live in a database (see api/db.py): SQLite locally, Postgres when
DATABASE_URL is set. Load existing results with `python -m api.seed`.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from api import db  # noqa: E402
from loader import Inbox  # noqa: E402
from src.cache import BudgetExceeded  # noqa: E402
from src.pipeline import analyze_comparison, process_email  # noqa: E402

SOURCE = os.environ.get("INBOX_SOURCE", "data")

app = FastAPI(title="Shipping document verification API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

_run = {"state": "idle", "done": 0, "total": 0, "failed": []}


def get_inbox() -> Inbox:
    return Inbox(SOURCE if SOURCE.startswith("http") or Path(SOURCE).is_absolute() else str(ROOT / SOURCE))


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
    return {"ok": True, "emails_processed": db.count_results()}


@app.get("/emails")
def list_emails(category: str | None = None, intent: str | None = None, status: str | None = None,
                q: str | None = None):
    inbox, decisions = get_inbox(), db.all_decisions()
    rows = []
    for email_id, entry in db.all_entries().items():
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
    stored = db.get_result(email_id)
    if stored is None:
        raise HTTPException(404, f"{email_id} has not been processed")
    entry = stored["entry"]
    inbox = get_inbox()
    email = inbox.get(email_id)
    result = merged(email_id, entry, db.all_decisions())
    result["email"] = {k: email[k] for k in ("subject", "from", "body", "attachments")}
    result["detail"] = stored["detail"]
    if result["detail"] is None and entry["category"] == "BL_COMPARISON":
        try:  # not stored yet: compute once (cached LLM results first), then keep it
            d = analyze_comparison(inbox, email)
            result["detail"] = {k: v for k, v in d.items() if k != "entry"}
            db.save_detail(email_id, result["detail"])
        except Exception as e:  # BudgetExceeded / API failure: keep the page usable
            result["detail_error"] = repr(e)
    return result


class Decision(BaseModel):
    status: str  # OK or MISMATCH
    defect_fields: list[str] = []
    note: str = ""


@app.post("/emails/{email_id}/review")
def submit_review(email_id: str, body: Decision):
    stored = db.get_result(email_id)
    if stored is None:
        raise HTTPException(404, f"{email_id} has not been processed")
    if body.status not in ("OK", "MISMATCH"):
        raise HTTPException(422, "status must be OK or MISMATCH")
    db.save_decision(email_id, body.status, body.defect_fields, body.note)
    return merged(email_id, stored["entry"], db.all_decisions())


def process_and_save(email_ids: list[str]) -> None:
    inbox = get_inbox()
    _run.update(state="running", done=0, total=len(email_ids), failed=[])
    for email_id in email_ids:
        try:
            out = process_email(inbox, inbox.get(email_id))
            detail = {k: v for k, v in out.items() if k != "entry"} or None
            db.save_result(email_id, out["entry"], detail, keep_detail=False)
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
    done = db.all_entries()
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
