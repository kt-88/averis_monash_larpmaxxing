"""Build a single report entry matching sample_submission.json's shape. No AI here."""
from src.comparator import NO_MISMATCH


def build_report_entry(category: str, mismatches=None, escalation: dict = None) -> dict:
    """Assemble the output dict for one email.

    For non-comparison categories, mismatch fields are left null and
    escalation defaults to not-flagged.
    """
    escalation = escalation or {"flagged": False, "reason": None}

    if category != "document-comparison":
        return {
            "category": category,
            "mismatch_found": None,
            "mismatches": None,
            "escalation": escalation,
        }

    mismatch_found = mismatches is not None and mismatches != NO_MISMATCH
    return {
        "category": category,
        "mismatch_found": mismatch_found,
        "mismatches": mismatches if mismatches is not None else NO_MISMATCH,
        "escalation": escalation,
    }
