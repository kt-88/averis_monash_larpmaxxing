"""Deterministic escalation checks. No AI here."""
from src.extractor import FIELD_KEYS


def check_escalation(si_fields: dict = None, bl_fields: dict = None, read_errors: list = None) -> dict:
    """Return {"flagged": bool, "reason": str | None}.

    Flags when any of the 7 fields is missing/null in either document, or
    when an attachment could not be read.

    STUB: reasons are a rough first draft, no severity levels yet.
    """
    read_errors = read_errors or []
    reasons = []

    if read_errors:
        reasons.extend(read_errors)

    for label, fields in (("SI", si_fields), ("BL", bl_fields)):
        if fields is None:
            continue
        for key in FIELD_KEYS:
            if fields.get(key) in (None, ""):
                reasons.append(f"{key} missing from {label}")

    if not reasons:
        return {"flagged": False, "reason": None}
    return {"flagged": True, "reason": "; ".join(reasons)}
