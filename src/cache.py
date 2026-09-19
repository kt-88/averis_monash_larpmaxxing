"""Disk cache + call counter for LLM calls."""
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


class BudgetExceeded(Exception):
    """Raised instead of making an API call once the call budget is used up."""


def set_call_budget(max_calls: int | None) -> None:
    _budget["max_calls"] = max_calls


def cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode("utf-8")).hexdigest()


def cache_get(key: str):
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        with _lock:
            stats["cache_hits"] += 1
        return json.loads(path.read_text(encoding="utf-8"))["response"]
    return None


def cache_put(key: str, response: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps({"response": response}), encoding="utf-8")


def cached_llm_call(model: str, prompt: str, call_fn) -> str:
    """Return the cached response for (model, prompt), else call_fn() and cache it."""
    key = cache_key(model, prompt)
    hit = cache_get(key)
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
