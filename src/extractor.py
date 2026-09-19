"""Stage 2: extract the 7 comparison fields from a document's text."""
import json
import os
import re
from pathlib import Path

from src.cache import BudgetExceeded
from src.labels import parse_line
from src.llm import llm_json_text
from src.normalize import is_blank, normalize

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


def _llm_extract(text: str, model: str | None = None) -> dict:
    """Ask the LLM. Returns {field: (value, snippet)}. value None = label absent, BLANK = present but blank."""
    model = model or os.environ.get("EXTRACT_MODEL", "gemini-3.5-flash-lite")
    prompt = PROMPT_PATH.read_text(encoding="utf-8").format(document_text=text)
    try:
        data = json.loads(llm_json_text(model, prompt))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for f in FIELDS:
        item = data.get(f)
        value, snippet = (item.get("value"), item.get("snippet")) if isinstance(item, dict) else (item, None)
        if isinstance(value, str) and PLACEHOLDER.match(value.strip()):
            value = BLANK
        out[f] = (value, str(snippet) if snippet else None)
    return out


def regex_extract(text: str) -> dict:
    """Find each field by its label. Returns {field: {"raw": value, "snippet": source line}}."""
    lines, found = text.splitlines(), {}
    for i, line in enumerate(lines):
        hit = parse_line(line)
        if not hit or hit[0] in found:               # first occurrence wins
            continue
        field, raw = hit
        if not raw and i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
            raw = lines[i + 1].strip()                # value on the next, indented line
        found[field] = {"raw": raw, "snippet": line.strip()}
    return found


def _in_text(needle, text: str) -> bool:
    """Is this snippet really in the source? (ignores case and extra spaces)"""
    squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return bool(needle) and squash(needle) in squash(text)


def _valid(field: str, v) -> bool:
    """Does the value look sane for its field?"""
    if field == "gross_weight_kg":
        return 0 < v < 1_000_000
    if field == "container_count":
        return 1 <= v <= 500
    return isinstance(v, str) and bool(re.search(r"[A-Z]{2}", v))


def build_field(field: str, text: str, rx, llm=None) -> dict:
    """rx: regex hit or None. llm: (value, snippet) from the LLM, or None if it wasn't asked."""
    rx_val = normalize(field, rx["raw"]) if rx else None
    llm_asked = llm is not None
    llm_raw, llm_snip = llm if llm_asked else (None, None)
    llm_val = normalize(field, llm_raw) if llm_raw and llm_raw != BLANK else None
    label_found = bool(rx) or (llm_asked and llm_raw is not None)

    raw = snippet = normalized = None
    if rx_val is not None:                               # regex parsed it: trust it
        raw, snippet, normalized = rx["raw"], rx["snippet"], rx_val
    elif llm_val is not None and _in_text(llm_snip, text):   # LLM value must be traceable
        raw, snippet, normalized = llm_raw, llm_snip, llm_val

    if normalized is None:                               # blank or absent: never guess
        if llm_val is not None:  conf = 0.2              # LLM said something we couldn't verify
        elif rx:                 conf = 0.9              # saw the label, value is blank
        elif label_found:        conf = 0.6
        else:                    conf = 0.9 if llm_asked else 0.5   # label absent
    else:
        conf = 0.0
        conf += 0.35 if _in_text(snippet, text) else 0   # snippet really is in the source
        conf += 0.25 if _valid(field, normalized) else 0 # value parses and looks sane
        conf += 0.10 if rx else 0                        # label was found
        if not llm_asked:
            conf += 0.15                                 # single source, unchecked
        elif llm_val == normalized:
            conf += 0.30                                 # regex and LLM agree
        else:
            conf = min(conf, 0.4)                        # they disagree
    return {"value": raw, "normalized": normalized, "confidence": round(conf, 2),
            "snippet": snippet, "label_found": label_found}


def _needs_llm(rx: dict) -> bool:
    """Only spend an API call when the regex could not settle every field."""
    if os.environ.get("VERIFY_WITH_LLM") == "1":
        return True
    for f in FIELDS:
        hit = rx.get(f)
        if hit is None:                                              # label not found by regex
            return True
        if not is_blank(hit["raw"]) and normalize(f, hit["raw"]) is None:   # found but unparseable
            return True
    return False


def extract_fields_detailed(text: str, model: str | None = None) -> dict:
    rx = regex_extract(text)
    llm = {}
    if _needs_llm(rx):
        try:
            llm = _llm_extract(text, model)
        except BudgetExceeded:
            raise                                                    # not a document problem
        except Exception as e:                                       # API down etc.: fall back to regex only
            print(f"[extractor] LLM unavailable, using regex only: {e!r}", flush=True)
    return {f: build_field(f, text, rx.get(f), llm.get(f)) for f in FIELDS}


def flat_values(detail: dict) -> dict:
    """{field: normalized value}, the old shape that comparator/escalation/viewer expect."""
    return {f: detail[f]["normalized"] for f in FIELDS}


def extract_fields(text: str, model: str | None = None) -> dict:
    return flat_values(extract_fields_detailed(text, model))
