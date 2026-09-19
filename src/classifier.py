"""Stage 1: classify an email into one of five categories."""
import json
import os
import re
from pathlib import Path

from src.llm import llm_json_text

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
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


def parse_category(raw: str) -> str:
    try:
        value = json.loads(raw).get("category", "")
    except (json.JSONDecodeError, AttributeError):
        value = raw
    value = str(value).strip().upper()
    for cat in CATEGORIES:
        if cat in value:
            return cat
    return "GENERAL"


def classify_email(email: dict, model: str | None = None) -> str:
    model = model or os.environ.get("CLASSIFY_MODEL", "gemini-3.5-flash-lite")
    return parse_category(llm_json_text(model, build_prompt(email)))
