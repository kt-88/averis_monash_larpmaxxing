"""Thin Gemini wrapper: cached, retrying text generation."""
import os
import threading
import time

from src.cache import cached_llm_call

_client = None
_client_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = [0.0]


def wait_for_rate_slot() -> None:
    """Space real API requests so they stay under MAX_RPM (default 12) across all threads."""
    interval = 60.0 / float(os.environ.get("MAX_RPM", "12"))
    with _rate_lock:
        now = time.monotonic()
        start = max(now, _next_slot[0])
        _next_slot[0] = start + interval
    if start > now:
        time.sleep(start - now)


def retry_delay(err) -> float:
    """Seconds Gemini asks us to wait (RetryInfo), else 0."""
    try:
        for d in err.details["error"]["details"]:
            if d.get("@type", "").endswith("RetryInfo"):
                return float(d["retryDelay"].rstrip("s"))
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return 0.0


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            from google import genai
            from google.genai import types
            _client = genai.Client(
                api_key=os.environ.get("GEMINI_API_KEY"),
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return _client


def _generate(model: str, prompt: str, max_retries: int = 8) -> str:
    from google.genai import errors, types
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    for attempt in range(max_retries + 1):
        wait_for_rate_slot()
        try:
            resp = _get_client().models.generate_content(model=model, contents=prompt, config=config)
            return resp.text or ""
        except (errors.ClientError, errors.ServerError) as e:
            if e.code in (429, 500, 503) and attempt < max_retries:
                time.sleep(max(retry_delay(e), min(30, 2 ** attempt * 2)))
                continue
            raise


def llm_json_text(model: str, prompt: str) -> str:
    return cached_llm_call(model, prompt, lambda: _generate(model, prompt))
