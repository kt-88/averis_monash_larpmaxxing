"""Build the per-email submission entry."""

STATUSES = ["OK", "MISMATCH", "NEEDS_REVIEW"]
REVIEW_REASONS = ["missing_attachment", "wrong_doc_type", "unreadable", "missing_value"]


def build_entry(category: str, status: str = "OK", review_reason: str | None = None,
                defect_fields: list[str] | None = None) -> dict:
    return {
        "category": category,
        "status": status,
        "review_reason": review_reason,
        "defect_fields": defect_fields or [],
        "has_defect": status == "MISMATCH",
    }
