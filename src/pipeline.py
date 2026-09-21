"""Orchestration: classify -> extract -> compare -> escalate -> report."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src import cache
from src.cache import BudgetExceeded
from src.classifier import classify_email
from src.comparator import compare_fields
from src.escalation import check_attachments, check_doc_types, check_missing_values, excusable_blanks
from src.extractor import extract_fields_detailed, flat_values
from src.readers import read_attachment
from src.report import build_entry


def load_documents(inbox, paths: list[str]) -> tuple[list[str], bool, bool]:
    """Read up to two attachments. Returns (texts read so far, any_unreadable, any_file_missing)."""
    texts = []
    for p in paths[:2]:
        try:
            texts.append(read_attachment(p, inbox.read_bytes(p)))
        except FileNotFoundError:
            return texts, False, True
        except BudgetExceeded:
            raise
        except Exception:  # UnreadableAttachment or any reader bug: escalate this email, don't crash the run
            return texts, True, False
    return texts, False, False


def analyze_comparison(inbox, email: dict, intent: str | None = None, title: str | None = None,
                       learned=()) -> dict:
    """Run stages 2-4 for one BL_COMPARISON email; returns entry plus readable source data.
    `learned`: fields reviewers have repeatedly accepted as blank on the SI (see src/learning.py)."""
    paths = email.get("attachments", [])
    detail = {"si_fields": None, "bl_fields": None, "si_text": None, "bl_text": None,
              "si_detail": None, "bl_detail": None, "learned_exceptions": []}

    def review(reason):
        return {**detail, "entry": build_entry("BL_COMPARISON", "NEEDS_REVIEW", reason, intent=intent, title=title)}

    texts, unreadable, file_missing = load_documents(inbox, paths)
    detail["si_text"] = texts[0] if texts else None
    detail["bl_text"] = texts[1] if len(texts) > 1 else None
    if file_missing:
        return review("missing_attachment")
    if (reason := check_attachments(paths)):
        return review(reason)
    if unreadable:
        return review("unreadable")
    if (reason := check_doc_types(*texts)):
        return review(reason)
    detail["si_detail"] = extract_fields_detailed(texts[0])
    detail["bl_detail"] = extract_fields_detailed(texts[1])
    detail["si_fields"], detail["bl_fields"] = flat_values(detail["si_detail"]), flat_values(detail["bl_detail"])
    excused = excusable_blanks(detail["si_fields"], detail["bl_fields"], learned)
    detail["learned_exceptions"] = excused
    if (reason := check_missing_values(detail["si_fields"], detail["bl_fields"], learned)):
        return review(reason)
    status, defects = compare_fields(detail["si_fields"], detail["bl_fields"], skip=excused)
    return {**detail, "entry": build_entry("BL_COMPARISON", status, None, defects, intent, title)}


def process_email(inbox, email: dict, learned=()) -> dict:
    category, intent, title = classify_email(email)
    if category != "BL_COMPARISON":
        return {"entry": build_entry(category, intent=intent, title=title)}
    return analyze_comparison(inbox, email, intent, title, learned)


def run_pipeline(inbox, limit: int | None = None, workers: int = 4) -> dict:
    emails = list(inbox)[:limit] if limit else list(inbox)
    def safe(e):
        try:
            return process_email(inbox, e)
        except BudgetExceeded:
            return None
        except Exception as err:  # one bad email must not lose the other 519
            print(f"[pipeline] {e.get('email_id')} failed and was skipped: {err!r}", flush=True)
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(safe, emails))
    skipped = sum(r is None for r in results)
    if skipped:
        print(f"[pipeline] {skipped} emails skipped (API budget reached or error): re-run to continue from cache")
    pairs = [(e, r) for e, r in zip(emails, results) if r is not None]
    emails, results = [e for e, _ in pairs], [r for _, r in pairs]
    print(f"[pipeline] done: {len(emails)} emails, {cache.stats['api_calls']} API calls, "
          f"{cache.stats['cache_hits']} cache hits", flush=True)
    return {e["email_id"]: r["entry"] for e, r in zip(emails, results)}


def save_submission(submission: dict, out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
