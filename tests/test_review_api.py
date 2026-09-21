"""API behaviour around human review and learned rules. Uses a temporary SQLite file and stubs the pipeline, so
it needs no Gemini key and never touches DATABASE_URL."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FULL = {"shipper": "A CO", "consignee": "B CO", "notify_party": "B CO", "port_of_loading": "NANTONG",
        "port_of_discharge": "KARACHI", "container_count": 6, "gross_weight_kg": 131058}
NO_WEIGHT = {**FULL, "gross_weight_kg": None}
ENTRY = {"category": "BL_COMPARISON", "intent": "check_docs", "title": "Stored title", "status": "NEEDS_REVIEW",
         "review_reason": "missing_value", "defect_fields": [], "has_defect": False}
DETAIL = {"si_fields": NO_WEIGHT, "bl_fields": FULL, "si_text": "si", "bl_text": "bl", "learned_exceptions": []}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A fresh api.db / api.main pair bound to a temporary SQLite database."""
    real = sa.create_engine
    monkeypatch.setattr(sa, "create_engine", lambda url, **kw: real(f"sqlite:///{(tmp_path / 't.db').as_posix()}"))
    for name in ("api.db", "api.main"):
        sys.modules.pop(name, None)
    db = importlib.import_module("api.db")
    main = importlib.import_module("api.main")
    yield db, main, TestClient(main.app)
    for name in ("api.db", "api.main"):
        sys.modules.pop(name, None)


def vote(client, email_id, blanks, reason="blank_acceptable"):
    return client.post(f"/emails/{email_id}/review",
                       json={"status": "OK", "reason": reason, "accepted_blanks": blanks})


def test_backend_accepts_a_review_without_a_reason(api):
    db, _, client = api
    db.save_result("email_001", ENTRY, DETAIL)
    res = client.post("/emails/email_001/review", json={"status": "OK"})   # an older frontend sends no reason
    assert res.status_code == 200
    assert db.all_decisions()["email_001"]["reason"] is None
    assert db.learned_blanks() == set()   # and such a decision teaches nothing


def test_an_unknown_reason_is_rejected(api):
    db, _, client = api
    db.save_result("email_001", ENTRY, DETAIL)
    assert client.post("/emails/email_001/review", json={"status": "OK", "reason": "bogus"}).status_code == 422


def test_a_vote_must_cover_real_blanks(api):
    db, _, client = api
    db.save_result("email_001", ENTRY, DETAIL)
    assert vote(client, "email_001", ["consignee"]).status_code == 422        # not blank on this email
    assert vote(client, "email_001", []).status_code == 422                   # nothing accepted
    assert vote(client, "email_001", ["nope"]).status_code == 422             # not a field at all
    assert vote(client, "email_001", ["gross_weight_kg"]).status_code == 200
    assert db.all_decisions()["email_001"]["accepted_blanks"] == ["gross_weight_kg"]


def test_a_vote_needs_the_email_details_loaded(api):
    db, _, client = api
    db.save_result("email_001", ENTRY, None)   # processed, but its fields were never stored
    assert vote(client, "email_001", ["gross_weight_kg"]).status_code == 422


def test_a_blank_bl_can_never_be_voted_acceptable(api):
    db, _, client = api
    db.save_result("email_001", ENTRY, {**DETAIL, "bl_fields": NO_WEIGHT})   # blank on both sides
    assert vote(client, "email_001", ["gross_weight_kg"]).status_code == 422


def test_learning_a_rule_reprocesses_waiting_emails_without_reclassifying(api, monkeypatch):
    db, main, client = api
    for voter in ("email_001", "email_002"):
        db.save_result(voter, ENTRY, DETAIL)
    db.save_result("email_003", {**ENTRY, "title": "Stored title 3"}, DETAIL)   # waiting on the same blank

    calls = []

    def fake_analyze(inbox, email, intent=None, title=None, learned=()):
        calls.append((email["email_id"], intent, title, set(learned)))
        entry = {**ENTRY, "status": "OK", "review_reason": None, "intent": intent, "title": title}
        return {"entry": entry, "learned_exceptions": ["gross_weight_kg"], "si_fields": NO_WEIGHT, "bl_fields": FULL}

    def no_classification(*args, **kwargs):
        raise AssertionError("reprocessing for a rule must not classify again")

    monkeypatch.setattr(main, "analyze_comparison", fake_analyze)
    monkeypatch.setattr(main, "process_email", no_classification)

    assert vote(client, "email_001", ["gross_weight_kg"]).status_code == 200
    assert calls == []                                                        # one vote is not a rule yet
    assert vote(client, "email_002", ["gross_weight_kg"]).status_code == 200

    assert calls == [("email_003", "check_docs", "Stored title 3", {"gross_weight_kg"})]   # stored intent/title reused
    row = {r["email_id"]: r for r in client.get("/emails").json()["emails"]}["email_003"]
    assert (row["status"], row["review_reason"], row["learned_rule"]) == ("OK", None, ["gross_weight_kg"])
