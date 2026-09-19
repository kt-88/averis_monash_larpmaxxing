"""Orchestrates classification, extraction, comparison, and escalation.

Assumes each email record from the loader has at least: "email_id",
"subject", "body", and "attachments" (a list of file paths). Adjust
_find_attachment / _process_comparison_email once the real loader.py
and data bundle are available and the actual schema is known.
"""
from src.classifier import classify_email
from src.extractor import extract_fields
from src.comparator import compare_fields
from src.escalation import check_escalation
from src.report import build_report_entry


def _find_attachment(email: dict, *keywords: str):
    for path in email.get("attachments", []):
        lowered = path.lower()
        if any(kw.lower() in lowered for kw in keywords):
            return path
    return None


def _process_comparison_email(email: dict, inbox) -> dict:
    si_path = _find_attachment(email, "SI", "shipping_instruction")
    bl_path = _find_attachment(email, "BL", "bill_of_lading")

    read_errors = []
    si_text = bl_text = ""

    if si_path:
        try:
            si_text = inbox.read_text(si_path)
        except Exception:
            read_errors.append("could not read SI attachment")
    else:
        read_errors.append("SI attachment not found")

    if bl_path:
        try:
            bl_text = inbox.read_text(bl_path)
        except Exception:
            read_errors.append("could not read BL attachment")
    else:
        read_errors.append("BL attachment not found")

    si_fields = extract_fields(si_text) if si_text else {}
    bl_fields = extract_fields(bl_text) if bl_text else {}

    mismatches = compare_fields(si_fields, bl_fields)
    escalation = check_escalation(si_fields, bl_fields, read_errors)

    return build_report_entry("document-comparison", mismatches, escalation)


def run_pipeline(inbox) -> dict:
    """Run classification (+ comparison where applicable) over the whole inbox."""
    output = {}

    for email in inbox:
        email_id = email["email_id"]
        category = classify_email(email)

        if category == "document-comparison":
            output[email_id] = _process_comparison_email(email, inbox)
        else:
            output[email_id] = build_report_entry(category)

    return output
