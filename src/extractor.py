"""Extract the 7 comparison fields from a document's raw text using an LLM."""
import json
from pathlib import Path

from google.genai import types

from src.gemini_client import generate_with_retry

MODEL = "gemini-2.5-flash"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_prompt.txt"
FIELD_KEYS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


def _strip_code_fence(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` despite instructions not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def extract_fields(doc_text: str) -> dict:
    """Extract the 7 fields from a document's text. Missing fields are None.

    STUB: prompt is a rough first draft.
    """
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.format(document_text=doc_text)

    response = generate_with_retry(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=500,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = _strip_code_fence(response.text or "")

    try:
        fields = json.loads(raw)
    except json.JSONDecodeError:
        fields = {}

    return {key: fields.get(key) for key in FIELD_KEYS}
