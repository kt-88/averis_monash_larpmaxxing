"""Disk cache + call counter for LLM calls."""
import contextlib
import contextvars
import hashlib
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", ROOT / ".cache" / "llm"))
_lock = threading.Lock()
stats = {"api_calls": 0, "cache_hits": 0}
_budget = {"max_calls": None}
_fresh = contextvars.ContextVar("llm_fresh", default=False)


class BudgetExceeded(Exception):
    """Raised instead of making an API call once the call budget is used up."""


def set_call_budget(max_calls: int | None) -> None:
    _budget["max_calls"] = max_calls


def cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode("utf-8")).hexdigest()


def cache_get(key: str):
    path = CACHE_DIR / f"{key}.json"
    try:
        response = json.loads(path.read_text(encoding="utf-8"))["response"]
    except (OSError, ValueError, KeyError):  # missing or half-written file -> treat as a cache miss
        return None
    if not isinstance(response, str) or not response.strip():
        return None
    with _lock:
        stats["cache_hits"] += 1
    return response


def cache_put(key: str, response: str) -> None:
    if not response or not response.strip():
        return  # never cache an empty answer
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f"{key}.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps({"response": response}), encoding="utf-8")
    os.replace(tmp, CACHE_DIR / f"{key}.json")  # atomic swap: no reader ever sees a half-written file


@contextlib.contextmanager
def fresh_llm_calls():
    """Inside this block saved answers are not read, so Gemini is asked again. The new answers are still saved,
    replacing the old ones (used by "re-run with Gemini")."""
    token = _fresh.set(True)
    try:
        yield
    finally:
        _fresh.reset(token)


def cached_llm_call(model: str, prompt: str, call_fn) -> str:
    """Return the cached response for (model, prompt), else call_fn() and cache it."""
    key = cache_key(model, prompt)
    hit = None if _fresh.get() else cache_get(key)
    if hit is not None:
        return hit
    with _lock:
        if _budget["max_calls"] is not None and stats["api_calls"] >= _budget["max_calls"]:
            raise BudgetExceeded(f"API call budget of {_budget['max_calls']} reached")
        stats["api_calls"] += 1
    response = call_fn()
    print(f"[llm] API calls made: {stats['api_calls']} (cache hits: {stats['cache_hits']})", flush=True)
    cache_put(key, response)
    return response
