"""Stage 1: classify an email into one of 5 categories."""
import json
import os
import re
from pathlib import Path

from src.llm import llm_json_text

INTENTS = {
    "BL_COMPARISON": ["check_docs"],
    "SI_REQUEST": ["si_submission"],
    "INVOICE_QUERY": ["missing_gr", "charges_breakdown", "detention_demurrage", "cancel_invoice", "other_invoice"],
    "GENERAL": ["chase_document", "automated_notice", "schedule_update", "other_general"],
    "SPAM": ["spam"],
}
CATEGORIES = list(INTENTS)
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify_prompt.txt"
THREAD_MARKER = re.compile(r"^\s*(_{5,}|-{5,}|From:\s|-+\s*Original Message)", re.M | re.I)
MAX_THREAD_CHARS = 2500


def split_body(body: str) -> tuple[str, str]:
    """Split into (newest message, quoted thread) at the first thread separator."""
    m = THREAD_MARKER.search(body)
    if not m or m.start() == 0:
        return body, ""
    return body[: m.start()], body[m.start():]


def build_prompt(email: dict) -> str:
    newest, thread = split_body(email.get("body", ""))
    return PROMPT_PATH.read_text(encoding="utf-8").format(
        subject=email.get("subject", ""), body=newest.strip(), thread=thread.strip()[:MAX_THREAD_CHARS]
    )


def parse_classification(raw: str, fallback_title: str = "") -> tuple[str, str, str]:
    """Return (category, intent, title); an intent that doesn't belong to the category falls back to its last one."""
    try:
        data = json.loads(raw)
        category, intent, title = data.get("category", ""), data.get("intent", ""), data.get("title", "")
    except (json.JSONDecodeError, AttributeError):
        category, intent, title = raw, "", ""
    category = str(category).strip().upper()
    category = next((c for c in CATEGORIES if c in category), "GENERAL")
    intent = str(intent).strip().lower()
    if intent not in INTENTS[category]:
        intent = INTENTS[category][-1]
    return category, intent, str(title or "").strip() or fallback_title


def classify_email(email: dict, model: str | None = None) -> tuple[str, str, str]:
    model = model or os.environ.get("CLASSIFY_MODEL", "gemini-3.5-flash-lite")
    return parse_classification(llm_json_text(model, build_prompt(email)), email.get("subject", ""))
