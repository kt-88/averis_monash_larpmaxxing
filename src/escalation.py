"""Stage 4: decide whether a comparison must go to a human, and why."""
from src.extractor import BLANK, FIELDS

OTHER_DOC_MARKERS = ["COMMERCIAL INVOICE", "PACKING LIST", "CERTIFICATE", "INVOICE"]


def detect_doc_type(text: str) -> str:
    """Classify by document title (first lines): SI, BL, OTHER, or UNKNOWN."""
    head = " ".join(text.strip().splitlines()[:4]).upper()
    if "BILL OF LADING" in head:
        return "BL"
    if any(m in head for m in OTHER_DOC_MARKERS):
        return "OTHER"
    if "SHIPPING INSTRUCTION" in head or "BL INSTRUCTION" in head or "S.I." in head:
        return "SI"
    return "UNKNOWN"


def missing_fields(fields: dict) -> list[str]:
    return [f for f in FIELDS if fields.get(f) is None or fields.get(f) == BLANK]


def check_attachments(attachment_paths: list[str]) -> str | None:
    return "missing_attachment" if len(attachment_paths) < 2 else None


def check_doc_types(si_text: str, bl_text: str) -> str | None:
    """wrong_doc_type if the second document is not recognisably a BL."""
    return "wrong_doc_type" if detect_doc_type(bl_text) in ("OTHER", "SI") else None


def excusable_blanks(si_fields: dict, bl_fields: dict, learned) -> list[str]:
    """Fields a reviewer rule excuses: blank in the SI, filled in on the BL. A blank BL is never excused."""
    si_blank, bl_blank = set(missing_fields(si_fields)), set(missing_fields(bl_fields))
    return [f for f in FIELDS if f in learned and f in si_blank and f not in bl_blank]


def check_missing_values(si_fields: dict, bl_fields: dict, learned=()) -> str | None:
    """missing_value unless every blank is one a reviewer rule excuses (see excusable_blanks)."""
    excused = set(excusable_blanks(si_fields, bl_fields, learned))
    missing = (set(missing_fields(si_fields)) | set(missing_fields(bl_fields))) - excused
    return "missing_value" if missing else None
