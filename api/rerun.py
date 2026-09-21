"""Re-run with Gemini: check one email again, for real.

    POST /emails/{id}/rerun

Unlike "retry" (which re-uses the saved Gemini answers, so it can only ever repeat itself), this ignores them and
asks Gemini again: it classifies the email afresh and, for a document comparison, has Gemini read the SI and the BL
as a second opinion on the fields the rules found. It then reports what changed and where Gemini disagreed.
A person's decision about the email is never touched. Failures leave the stored result exactly as it was.
Settings: RERUN_MAX_PER_HOUR caps the use of Gemini; the same email can be re-run at most once every 10 seconds.
"""
import os
import threading
import time
from collections import deque

from fastapi import APIRouter, HTTPException

from src import cache
from src.cache import BudgetExceeded, fresh_llm_calls
from src.extractor import FIELDS, cross_check_with_llm
from src.pipeline import process_email

COOLDOWN_SECONDS = 10
ENTRY_KEYS = ("category", "intent", "title", "status", "review_reason", "defect_fields")

_last: dict[str, float] = {}
_busy: set[str] = set()
_recent: deque[float] = deque()
_lock = threading.Lock()


def max_per_hour() -> int:
    return int(os.environ.get("RERUN_MAX_PER_HOUR", "60"))


def friendly_error(err: Exception) -> tuple[int, str]:
    text = repr(err)
    if isinstance(err, BudgetExceeded):
        return 429, "The Gemini call budget for this server was reached. Try again later."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return 429, "Gemini's free quota is used up for now (it resets daily). The stored result was not changed."
    return 502, f"Gemini could not be reached: {text[:200]}. The stored result was not changed."


def agreement_of(detail: dict) -> dict | None:
    """How Gemini's own reading of the SI and BL compared with the rules', or None if Gemini was never asked."""
    checked = agreed = 0
    disagreements = []
    for side in ("si", "bl"):
        for f, v in ((detail.get(f"{side}_detail")) or {}).items():
            if v.get("agree") is None:
                continue
            checked += 1
            if v["agree"]:
                agreed += 1
            else:
                disagreements.append({"side": side, "field": f, "system": v.get("normalized"), "gemini": v.get("llm")})
    return {"checked": checked, "agree": agreed, "disagreements": disagreements} if checked else None


def summarize(before_entry: dict, before_detail: dict | None, out: dict) -> dict:
    """What changed between the stored result and the fresh one, and where Gemini disagreed with the rules."""
    after = out["entry"]
    changes = [{"what": k, "before": before_entry.get(k), "after": after.get(k)}
               for k in ENTRY_KEYS if before_entry.get(k) != after.get(k)]

    field_changes = []
    for side in ("si", "bl"):
        was = ((before_detail or {}).get(f"{side}_fields")) or {}
        now = (out.get(f"{side}_fields")) or {}
        for f in FIELDS:
            if was and now and was.get(f) != now.get(f):
                field_changes.append({"side": side, "field": f, "before": was.get(f), "after": now.get(f)})

    return {"changed": bool(changes or field_changes), "changes": changes, "field_changes": field_changes,
            "agreement": agreement_of(out) or {"checked": 0, "agree": 0, "disagreements": []}}


def build_router(get_inbox) -> APIRouter:
    router = APIRouter(tags=["rerun"])

    @router.post("/emails/{email_id}/rerun")
    def rerun(email_id: str):
        from api import db   # looked up on every call so a reloaded api.db (tests) is the one used
        stored = db.get_result(email_id)
        if stored is None:
            raise HTTPException(404, f"{email_id} has not been processed")
        try:
            email = get_inbox().get(email_id)
        except KeyError:
            raise HTTPException(404, f"no such email: {email_id}") from None

        with _lock:
            now = time.time()
            wait = COOLDOWN_SECONDS - (now - _last.get(email_id, 0))
            if email_id in _busy:
                raise HTTPException(409, "this email is already being re-run")
            if wait > 0:
                raise HTTPException(429, f"this email was just re-run: wait {int(wait) + 1} seconds")
            while _recent and now - _recent[0] > 3600:
                _recent.popleft()
            if len(_recent) >= max_per_hour():
                raise HTTPException(429, f"limit reached: at most {max_per_hour()} re-runs per hour")
            _recent.append(now)
            _busy.add(email_id)

        calls_before = cache.stats["api_calls"]
        try:
            with fresh_llm_calls(), cross_check_with_llm():
                out = process_email(get_inbox(), email, db.learned_blanks())
            detail = {k: v for k, v in out.items() if k != "entry"} or None
            db.save_result(email_id, out["entry"], detail, keep_detail=False)
        except Exception as err:
            status, message = friendly_error(err)
            raise HTTPException(status, message) from err
        finally:
            with _lock:
                _busy.discard(email_id)
                _last[email_id] = time.time()

        summary = summarize(stored["entry"], stored["detail"], out)
        return {"email_id": email_id, "gemini_calls": cache.stats["api_calls"] - calls_before,
                "category": out["entry"]["category"], "status": out["entry"]["status"], **summary}

    return router
