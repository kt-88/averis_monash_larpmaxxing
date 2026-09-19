"""Shared Gemini client + retry helper for classifier.py and extractor.py."""
import os
import time

from google import genai
from google.genai import errors

_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


def generate_with_retry(model: str, contents: str, config, max_retries: int = 5):
    """Call generate_content, retrying on 429 (free-tier rate limit) with backoff."""
    for attempt in range(max_retries + 1):
        try:
            return get_client().models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.ClientError as e:
            if e.code == 429 and attempt < max_retries:
                time.sleep(2 ** attempt * 5)
                continue
            raise
