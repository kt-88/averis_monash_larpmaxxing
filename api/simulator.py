"""Email simulator: compose an email (with SI / BL attachments) and have the real pipeline process it.

    POST   /simulate/emails        store the email and start processing it in the background
    GET    /simulate/emails/{id}   processing | done | failed
    DELETE /simulate/emails/{id}   remove a simulated email and everything stored about it
    GET    /simulate/info          whether the simulator is on, and its limits

Simulated emails go through exactly the same stages as the provided ones (classify, extract, compare, escalate)
and show up in the normal inbox, tagged by their sim_ id. They never enter output/submission.json.
Settings: SIMULATOR_ENABLED=0 switches it off; SIM_MAX_PER_HOUR, SIM_MAX_STORED cap the use of Gemini and storage.
"""
import base64
import binascii
import os
import re
import threading
import time
from collections import deque

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api import sim_store
from api.rerun import agreement_of
from src.cache import BudgetExceeded
from src.extractor import cross_check_with_llm
from src.pipeline import process_email

ALLOWED_SUFFIXES = (".txt", ".pdf", ".docx", ".xlsx")
MAX_ATTACHMENTS = 3
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_SUBJECT, MAX_BODY, MAX_SENDER = 300, 20_000, 200

_state: dict[str, dict] = {}       # email_id -> {"state": "processing" | "done" | "failed", "error": ...}
_recent: deque[float] = deque()    # when recent simulated emails were sent (for the hourly cap)
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("SIMULATOR_ENABLED", "1") != "0"


def max_per_hour() -> int:
    return int(os.environ.get("SIM_MAX_PER_HOUR", "30"))


def max_stored() -> int:
    return int(os.environ.get("SIM_MAX_STORED", "200"))


class SimAttachment(BaseModel):
    filename: str
    content_base64: str


class SimEmail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    sender: str = Field(alias="from", default="simulator@example.com")
    subject: str = ""
    body: str = ""
    attachments: list[SimAttachment] = []


def clean_files(attachments: list[SimAttachment]) -> list[tuple[str, bytes]]:
    """Check and decode the attachments. Raises HTTP 422 with a plain-language reason."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(422, f"attach at most {MAX_ATTACHMENTS} files")
    files = []
    for a in attachments:
        name = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", os.path.basename(a.filename.replace("\\", "/"))).strip(" .")
        if not name.lower().endswith(ALLOWED_SUFFIXES):
            raise HTTPException(422, f"{a.filename!r}: only {', '.join(ALLOWED_SUFFIXES)} files can be attached")
        try:
            data = base64.b64decode(a.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, f"{a.filename!r}: the file content is not valid base64") from None
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(422, f"{a.filename!r} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        files.append((name[:120], data))
    return files


def friendly_error(err: Exception) -> str:
    text = repr(err)
    if isinstance(err, BudgetExceeded):
        return "The Gemini call budget for this server was reached. Try again later."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "Gemini's free quota is used up for now (it resets daily). Try again later."
    return f"Processing failed: {text[:200]}"


def process_with_second_opinion(inbox, email: dict, learned):
    """Process like any other email, and also let Gemini read the documents on its own as a second opinion.
    The second opinion is a bonus: if it cannot be had, the email is processed normally (the classification Gemini
    already gave is saved, so this costs no extra call)."""
    try:
        with cross_check_with_llm():
            return process_email(inbox, email, learned)
    except BudgetExceeded:
        raise
    except Exception:
        return process_email(inbox, email, learned)


def build_router(get_inbox) -> APIRouter:
    router = APIRouter(prefix="/simulate", tags=["simulator"])

    def need_enabled() -> None:
        if not enabled():
            raise HTTPException(404, "the email simulator is switched off on this server")

    def process(email_id: str) -> None:
        from api import db   # looked up on every call so a reloaded api.db (tests) is the one used
        _state[email_id] = {"state": "processing"}
        try:
            inbox = get_inbox()
            out = process_with_second_opinion(inbox, inbox.get(email_id), db.learned_blanks())
            detail = {k: v for k, v in out.items() if k != "entry"} or None
            db.save_result(email_id, out["entry"], detail, keep_detail=False)
            _state[email_id] = {"state": "done"}
        except Exception as err:   # no half-processed email stays behind: the sender can fix the draft and resend
            sim_store.delete_email(email_id)
            _state[email_id] = {"state": "failed", "error": friendly_error(err)}

    @router.get("/info")
    def info():
        return {"enabled": enabled(), "allowed": list(ALLOWED_SUFFIXES), "max_attachments": MAX_ATTACHMENTS,
                "max_file_mb": MAX_FILE_BYTES // (1024 * 1024), "max_per_hour": max_per_hour(),
                "stored": sim_store.count() if enabled() else 0}

    @router.post("/emails")
    def send(body: SimEmail, background: BackgroundTasks):
        need_enabled()
        subject, text, sender = body.subject.strip(), body.body.strip(), body.sender.strip()
        if not subject and not text:
            raise HTTPException(422, "write a subject or a message first")
        if len(subject) > MAX_SUBJECT or len(text) > MAX_BODY or len(sender) > MAX_SENDER:
            raise HTTPException(422, "the subject, message or sender is too long")
        files = clean_files(body.attachments)
        with _lock:
            now = time.time()
            while _recent and now - _recent[0] > 3600:
                _recent.popleft()
            if len(_recent) >= max_per_hour():
                raise HTTPException(429, f"limit reached: at most {max_per_hour()} simulated emails per hour")
            if sim_store.count() >= max_stored():
                raise HTTPException(429, "too many simulated emails are stored: delete some first")
            _recent.append(now)
        email = sim_store.add_email(sender or "simulator@example.com", subject, text, files)
        _state[email["email_id"]] = {"state": "processing"}
        background.add_task(process, email["email_id"])
        return {"email_id": email["email_id"], "state": "processing", "attachments": len(files)}

    @router.get("/emails/{email_id}")
    def status(email_id: str):
        from api import db
        need_enabled()
        known = _state.get(email_id)
        if known and known["state"] == "failed":
            return {"email_id": email_id, **known}
        result = db.get_result(email_id)
        if result:
            return {"email_id": email_id, "state": "done", "entry": result["entry"],
                    "second_opinion": agreement_of(result["detail"] or {})}
        if sim_store.get_email(email_id):
            return {"email_id": email_id, "state": "processing"}
        raise HTTPException(404, f"no simulated email {email_id}")

    @router.delete("/emails/{email_id}")
    def remove(email_id: str):
        need_enabled()
        if not sim_store.is_simulated(email_id) or not sim_store.delete_email(email_id):
            raise HTTPException(404, f"no simulated email {email_id}")
        _state.pop(email_id, None)
        return {"deleted": email_id}

    return router
