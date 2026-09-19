"""Shape-only test: runs the pipeline against data/ and checks output structure.

Does not assert business correctness (mismatch accuracy, classification
correctness) - just that every email produced a well-formed entry.
"""
import itertools

import pytest

loader = pytest.importorskip("loader", reason="loader.py not present yet")

from src.pipeline import run_pipeline

REQUIRED_KEYS = {"category", "mismatch_found", "mismatches", "escalation"}


class _LimitedInbox:
    """Wraps a real Inbox but only iterates its first N emails.

    read_text/submit are delegated straight through so extraction still
    works against the real data files.
    """

    def __init__(self, inbox, limit):
        self._inbox = inbox
        self._limit = limit

    def __iter__(self):
        return itertools.islice(iter(self._inbox), self._limit)

    def read_text(self, path):
        return self._inbox.read_text(path)

    def submit(self, output_dict):
        return self._inbox.submit(output_dict)


def test_output_has_entry_per_email_with_required_keys():
    inbox = loader.Inbox("data")
    limited = _LimitedInbox(inbox, limit=3)
    email_ids = {email["email_id"] for email in limited}
    assert email_ids, "no emails found in data/ - add the extracted bundle first"

    output = run_pipeline(limited)

    assert set(output.keys()) == email_ids

    for entry in output.values():
        assert REQUIRED_KEYS.issubset(entry.keys())
        assert "flagged" in entry["escalation"]
        assert "reason" in entry["escalation"]
