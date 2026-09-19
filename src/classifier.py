"""Classify inbox emails into one of five categories using an LLM."""
from pathlib import Path

from google.genai import types

from src.gemini_client import generate_with_retry

MODEL = "gemini-2.5-flash"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify_prompt.txt"
VALID_CATEGORIES = {
    "document-comparison",
    "new-SI-request",
    "invoice-query",
    "general",
    "spam",
}


def classify_email(email: dict) -> str:
    """Classify a single email record. Returns one of VALID_CATEGORIES.

    STUB: prompt is a rough first draft.
    """
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.format(
        subject=email.get("subject", ""),
        body=email.get("body", ""),
    )

    response = generate_with_retry(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=20,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    category = (response.text or "").strip()

    if category not in VALID_CATEGORIES:
        return "general"
    return category
