"""Stage 2: extract the 7 comparison fields from a document's text."""
import json
import os
import re
from pathlib import Path

from src.llm import llm_json_text

FIELDS = [
    "shipper", "consignee", "notify_party", "port_of_loading",
    "port_of_discharge", "container_count", "gross_weight_kg",
]
BLANK = "BLANK"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_prompt.txt"
PLACEHOLDER = re.compile(r"^[\s_\-?.]*$|^(TBA|TBC|TBD|N/?A|NIL|NONE|BLANK)$", re.I)


def normalize_result(data: dict) -> dict:
    """Keep exactly the 7 fields; map empty/placeholder strings to BLANK, absent to None."""
    out = {}
    for f in FIELDS:
        v = data.get(f) if isinstance(data, dict) else None
        if isinstance(v, str) and PLACEHOLDER.match(v.strip()):
            v = BLANK
        out[f] = v
    return out


def parse_extraction(raw: str) -> dict:
    try:
        return normalize_result(json.loads(raw))
    except json.JSONDecodeError:
        return {f: None for f in FIELDS}


def extract_fields(text: str, model: str | None = None) -> dict:
    model = model or os.environ.get("EXTRACT_MODEL", "gemini-3.5-flash-lite")
    prompt = PROMPT_PATH.read_text(encoding="utf-8").format(document_text=text)
    return parse_extraction(llm_json_text(model, prompt))
