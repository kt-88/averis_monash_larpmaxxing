"""The email simulator and "re-run with Gemini" endpoints.

They use a temporary SQLite file, the real reader / extractor / comparator / escalation, and stub only the calls to
Gemini, so they need no API key and never touch DATABASE_URL.
"""
import base64
import importlib
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
import openpyxl  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MODULES = ("api.db", "api.sim_store", "api.livebox", "api.simulator", "api.rerun", "api.main")

SI = """SHIPPING INSTRUCTION
Shipper/Exporter: NORTHWIND PAPER TRADING PTE LTD
  1 HARBOUR ROAD, SINGAPORE
CONSIGNEE: ACME STATIONERY LLC
NOTIFY PARTY: ACME STATIONERY LLC
Port of Loading: SINGAPORE
Discharge Port: KARACHI, PAKISTAN
No. of Containers or Packages: 6 x 40'HC
Gross Weight (KG): 131,058 KG
"""
BL = """BILL OF LADING (DRAFT)
SHIPPER: NORTHWIND PAPER TRADING PTE LTD
CONSIGNEE: ACME STATIONERY LLC
Notify: ACME STATIONERY LLC
Port of Loading (POL): SINGAPORE
POD: KARACHI, PAKISTAN
Container Count: 6 x 40'HC
Gross Wt (kgs): 131,058 KG
"""
CLASSIFIED = ("BL_COMPARISON", "check_docs", "Check draft BL vs SI")


def b64(data) -> str:
    return base64.b64encode(data.encode() if isinstance(data, str) else data).decode()


def attach(name, data):
    return {"filename": name, "content_base64": b64(data)}


def mail(subject="Please check the draft BL", atts=(), sender="ops@example.com", body="Dear team, please check."):
    return {"from": sender, "subject": subject, "body": body, "attachments": list(atts)}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A fresh set of api modules bound to a temporary SQLite database, with Gemini stubbed out."""
    real = sa.create_engine
    monkeypatch.setattr(sa, "create_engine", lambda url, **kw: real(f"sqlite:///{(tmp_path / 't.db').as_posix()}"))
    for name in MODULES:
        sys.modules.pop(name, None)
    for name in MODULES:                       # import them afresh, in this order, so api.main uses these copies
        module = importlib.import_module(name)
        if name == "api.db":
            db = module
    main = sys.modules["api.main"]

    import src.llm
    import src.pipeline as pipeline

    def no_network(*a, **k):
        raise AssertionError("a test tried to call the real Gemini")
    monkeypatch.setattr(src.llm, "_generate", no_network)
    monkeypatch.setattr(pipeline, "classify_email", lambda email, model=None: CLASSIFIED)
    monkeypatch.delenv("SIMULATOR_ENABLED", raising=False)
    yield db, main, TestClient(main.app), pipeline
    for name in MODULES:
        sys.modules.pop(name, None)


def send(client, **kw):
    res = client.post("/simulate/emails", json=mail(**kw))
    assert res.status_code == 200, res.text
    return res.json()["email_id"]


def status_of(client, email_id):
    return client.get(f"/simulate/emails/{email_id}").json()


# ---------- composing an email ----------
def test_a_matching_si_and_bl_is_processed_end_to_end(api):
    _, _, client, _ = api
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    assert email_id == "sim_0001"
    done = status_of(client, email_id)
    assert done["state"] == "done" and done["entry"]["status"] == "OK" and done["entry"]["category"] == "BL_COMPARISON"

    row = {r["email_id"]: r for r in client.get("/emails").json()["emails"]}[email_id]
    assert row["subject"] == "Please check the draft BL" and row["status"] == "OK"

    one = client.get(f"/emails/{email_id}").json()
    assert one["email"]["from"] == "ops@example.com"
    assert one["detail"]["si_fields"]["gross_weight_kg"] == 131058.0
    assert one["detail"]["bl_fields"]["port_of_loading"] == "SINGAPORE"
    assert "SHIPPING INSTRUCTION" in one["detail"]["si_text"]


def test_a_mismatch_is_found(api):
    _, _, client, _ = api
    other = BL.replace("ACME STATIONERY LLC", "OTHER TRADING CO")
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", other)])
    entry = status_of(client, email_id)["entry"]
    assert entry["status"] == "MISMATCH" and set(entry["defect_fields"]) == {"consignee", "notify_party"}


def test_a_missing_bl_needs_review(api):
    _, _, client, _ = api
    entry = status_of(client, send(client, atts=[attach("SI.txt", SI)]))["entry"]
    assert (entry["status"], entry["review_reason"]) == ("NEEDS_REVIEW", "missing_attachment")


def test_a_blank_value_is_not_guessed(api):
    _, _, client, _ = api
    blank = SI.replace("NOTIFY PARTY: ACME STATIONERY LLC", "NOTIFY PARTY: ???")
    entry = status_of(client, send(client, atts=[attach("SI.txt", blank), attach("BL.txt", BL)]))["entry"]
    assert (entry["status"], entry["review_reason"]) == ("NEEDS_REVIEW", "missing_value")


def test_a_corrupt_pdf_is_unreadable_not_a_crash(api):
    _, _, client, _ = api
    entry = status_of(client, send(client, atts=[attach("SI.txt", SI), attach("BL.pdf", b"%PDF-1.4 garbage")]))["entry"]
    assert (entry["status"], entry["review_reason"]) == ("NEEDS_REVIEW", "unreadable")


def test_an_excel_si_and_a_text_bl_work_together(api):
    _, _, client, _ = api
    wb = openpyxl.Workbook()
    ws = wb.active
    for label, value in [("SHIPPING INSTRUCTION", None), ("Shipper/Exporter", "NORTHWIND PAPER TRADING PTE LTD"),
                         ("CONSIGNEE", "ACME STATIONERY LLC"), ("NOTIFY PARTY", "ACME STATIONERY LLC"),
                         ("Port of Loading", "SINGAPORE"), ("Discharge Port", "KARACHI, PAKISTAN"),
                         ("Container Count", "6 x 40'HC"), ("Gross Weight (KG)", 131058)]:
        ws.append([label, value])
    buf = io.BytesIO()
    wb.save(buf)
    entry = status_of(client, send(client, atts=[attach("SI.xlsx", buf.getvalue()), attach("BL.txt", BL)]))["entry"]
    assert entry["status"] == "OK"


def test_an_email_without_attachments_is_classified_only(api, monkeypatch):
    _, _, client, pipeline = api
    monkeypatch.setattr(pipeline, "classify_email", lambda email, model=None: ("INVOICE_QUERY", "charges_breakdown", "Charges"))
    entry = status_of(client, send(client, subject="Query on charges for invoice 123"))["entry"]
    assert entry["category"] == "INVOICE_QUERY" and entry["status"] == "OK"


def test_ids_count_up_and_the_provided_inbox_still_works(api):
    db, _, client, _ = api
    assert [send(client, atts=[attach("SI.txt", SI)]) for _ in range(3)] == ["sim_0001", "sim_0002", "sim_0003"]
    db.save_result("email_001", {"category": "GENERAL", "intent": "other_general", "title": "t", "status": "OK",
                                 "review_reason": None, "defect_fields": [], "has_defect": False})
    assert client.get("/emails/email_001").status_code == 200          # a provided email is still read from disk
    assert len(client.get("/emails").json()["emails"]) == 4


# ---------- Gemini's second opinion happens automatically ----------
def gemini_mirrors_rules(monkeypatch, tweak=None):
    import src.extractor as extractor

    def reads(text, model=None):
        out = {f: (v["raw"], v["snippet"]) for f, v in extractor.regex_extract(text).items()}
        return tweak(text, out) if tweak else out
    monkeypatch.setattr(extractor, "_llm_extract", reads)


def test_a_composed_email_gets_gemini_second_opinion_without_asking(api, monkeypatch):
    _, _, client, _ = api
    gemini_mirrors_rules(monkeypatch)
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    done = status_of(client, email_id)
    assert done["second_opinion"] == {"checked": 14, "agree": 14, "disagreements": []}   # 7 fields x SI and BL
    detail = client.get(f"/emails/{email_id}").json()["detail"]
    assert detail["si_detail"]["consignee"]["agree"] is True and detail["si_detail"]["consignee"]["llm"] == "ACME STATIONERY LLC"


def test_the_second_opinion_shows_where_gemini_read_something_else(api, monkeypatch):
    _, _, client, _ = api

    def tweak(text, out):
        if "SHIPPING" in text:
            out["gross_weight_kg"] = ("999 KG", "Gross Weight (KG): 131,058 KG")
        return out
    gemini_mirrors_rules(monkeypatch, tweak)
    done = status_of(client, send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)]))
    assert done["entry"]["status"] == "OK"                                    # the document's value still decides
    assert done["second_opinion"]["disagreements"] == [
        {"side": "si", "field": "gross_weight_kg", "system": 131058.0, "gemini": 999.0}]


def test_no_second_opinion_is_needed_for_emails_without_documents(api, monkeypatch):
    _, _, client, pipeline = api
    monkeypatch.setattr(pipeline, "classify_email", lambda email, model=None: ("SPAM", "spam", "Spam"))
    done = status_of(client, send(client, subject="Win a prize"))
    assert done["state"] == "done" and done["second_opinion"] is None


def test_if_gemini_cannot_give_a_second_opinion_the_email_is_still_processed(api, monkeypatch):
    _, _, client, _ = api
    import src.extractor as extractor

    def down(text, model=None):
        raise RuntimeError("503 unavailable")
    monkeypatch.setattr(extractor, "_llm_extract", down)
    done = status_of(client, send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)]))
    assert done["state"] == "done" and done["entry"]["status"] == "OK" and done["second_opinion"] is None


# ---------- when it goes wrong ----------
def test_a_gemini_failure_is_reported_and_leaves_nothing_behind(api, monkeypatch):
    _, _, client, pipeline = api

    def quota(email, model=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(pipeline, "classify_email", quota)
    email_id = send(client, atts=[attach("SI.txt", SI)])
    failed = status_of(client, email_id)
    assert failed["state"] == "failed" and "quota" in failed["error"]
    assert client.get("/emails").json()["emails"] == []                # no half-processed email in the inbox
    assert send(client, atts=[attach("SI.txt", SI)]) == "sim_0001"     # and the id is free again


@pytest.mark.parametrize("payload,expected", [
    (mail(subject="", body=""), "subject or a message"),
    (mail(atts=[attach("notes.exe", "x")]), "only"),
    (mail(atts=[{"filename": "SI.txt", "content_base64": "not base64!!"}]), "base64"),
    (mail(atts=[attach("a.txt", "1")] * 4), "at most"),
])
def test_bad_input_is_rejected_in_plain_language(api, payload, expected):
    _, _, client, _ = api
    res = client.post("/simulate/emails", json=payload)
    assert res.status_code == 422 and expected in res.json()["detail"]


def test_a_file_that_is_too_large_is_rejected(api, monkeypatch):
    _, _, client, _ = api
    import api.simulator as simulator
    monkeypatch.setattr(simulator, "MAX_FILE_BYTES", 10)
    res = client.post("/simulate/emails", json=mail(atts=[attach("SI.txt", "x" * 11)]))
    assert res.status_code == 422 and "larger" in res.json()["detail"]


def test_file_names_cannot_escape_their_folder(api):
    _, _, client, _ = api
    email_id = send(client, atts=[attach("..\\..\\etc\\SI.txt", SI)])
    paths = client.get(f"/emails/{email_id}").json()["email"]["attachments"]
    assert paths == [f"sim/{email_id}/1_SI.txt"]


def test_the_hourly_limit_protects_the_gemini_quota(api, monkeypatch):
    _, _, client, _ = api
    monkeypatch.setenv("SIM_MAX_PER_HOUR", "2")
    send(client, atts=[attach("SI.txt", SI)])
    send(client, atts=[attach("SI.txt", SI)])
    res = client.post("/simulate/emails", json=mail(atts=[attach("SI.txt", SI)]))
    assert res.status_code == 429 and "per hour" in res.json()["detail"]


def test_the_simulator_can_be_switched_off(api, monkeypatch):
    _, _, client, _ = api
    monkeypatch.setenv("SIMULATOR_ENABLED", "0")
    assert client.get("/simulate/info").json()["enabled"] is False
    assert client.post("/simulate/emails", json=mail(atts=[attach("SI.txt", SI)])).status_code == 404


# ---------- cleaning up ----------
def test_deleting_removes_the_email_its_result_and_its_decision(api):
    db, _, client, _ = api
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    db.save_decision(email_id, "OK", [], "checked")
    assert client.delete(f"/simulate/emails/{email_id}").status_code == 200
    assert client.get("/emails").json()["emails"] == [] and email_id not in db.all_decisions()
    assert client.delete(f"/simulate/emails/{email_id}").status_code == 404
    assert client.delete("/simulate/emails/email_001").status_code == 404     # a provided email can never be deleted


# ---------- re-run with Gemini ----------
def rerun(client, email_id):
    return client.post(f"/emails/{email_id}/rerun")


def test_rerun_asks_gemini_afresh_and_reports_full_agreement(api, monkeypatch):
    _, _, client, pipeline = api
    from src import cache
    seen = []

    def classify(email, model=None):
        seen.append(cache._fresh.get())            # was this call allowed to use a saved answer?
        return CLASSIFIED
    monkeypatch.setattr(pipeline, "classify_email", classify)

    import src.extractor as extractor

    def gemini_reads(text, model=None):            # Gemini reads the document the same way the rules did
        return {f: (v["raw"], v["snippet"]) for f, v in extractor.regex_extract(text).items()}
    monkeypatch.setattr(extractor, "_llm_extract", gemini_reads)

    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    seen.clear()
    res = rerun(client, email_id)
    assert res.status_code == 200, res.text
    body = res.json()
    assert seen == [True]                                                   # saved answers were ignored
    assert body["changed"] is False and body["changes"] == [] and body["status"] == "OK"
    assert body["agreement"] == {"checked": 14, "agree": 14, "disagreements": []}   # 7 fields x SI and BL


def test_rerun_reports_where_gemini_disagrees_without_overriding_the_document(api, monkeypatch):
    _, _, client, _ = api
    import src.extractor as extractor

    def gemini_reads(text, model=None):
        out = {f: (v["raw"], v["snippet"]) for f, v in extractor.regex_extract(text).items()}
        if "SHIPPING" in text:
            out["consignee"] = ("SOMEONE ELSE LTD", "CONSIGNEE: ACME STATIONERY LLC")
        return out
    monkeypatch.setattr(extractor, "_llm_extract", gemini_reads)

    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    body = rerun(client, email_id).json()
    assert body["agreement"]["checked"] == 14 and body["agreement"]["agree"] == 13
    assert body["agreement"]["disagreements"] == [
        {"side": "si", "field": "consignee", "system": "ACME STATIONERY LLC", "gemini": "SOMEONE ELSE LTD"}]
    assert client.get(f"/emails/{email_id}").json()["detail"]["si_fields"]["consignee"] == "ACME STATIONERY LLC"


def test_rerun_shows_and_saves_what_changed(api, monkeypatch):
    _, _, client, pipeline = api
    import src.extractor as extractor
    monkeypatch.setattr(extractor, "_llm_extract", lambda text, model=None: {})      # Gemini adds nothing here
    monkeypatch.setattr(pipeline, "classify_email", lambda email, model=None: ("GENERAL", "other_general", "Old title"))
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    assert status_of(client, email_id)["entry"]["category"] == "GENERAL"

    monkeypatch.setattr(pipeline, "classify_email", lambda email, model=None: CLASSIFIED)
    body = rerun(client, email_id).json()
    assert body["changed"] is True
    assert {c["what"]: (c["before"], c["after"]) for c in body["changes"]}["category"] == ("GENERAL", "BL_COMPARISON")
    assert client.get("/emails").json()["emails"][0]["category"] == "BL_COMPARISON"          # the fresh result was saved


def test_rerun_keeps_a_persons_decision(api):
    db, _, client, _ = api
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    db.save_decision(email_id, "MISMATCH", ["consignee"], "I checked")
    rerun(client, email_id)
    assert db.all_decisions()[email_id]["note"] == "I checked"
    assert client.get(f"/emails/{email_id}").json()["human_decision"]["status"] == "MISMATCH"


def test_rerun_failure_leaves_the_stored_result_untouched(api, monkeypatch):
    _, _, client, pipeline = api
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    before = client.get(f"/emails/{email_id}").json()

    def quota(email, model=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(pipeline, "classify_email", quota)
    res = rerun(client, email_id)
    assert res.status_code == 429 and "not changed" in res.json()["detail"]
    assert client.get(f"/emails/{email_id}").json() == before


def test_rerun_cross_check_failure_is_an_error_not_a_fake_agreement(api, monkeypatch):
    _, _, client, _ = api
    import src.extractor as extractor

    def down(text, model=None):
        raise RuntimeError("503 unavailable")
    monkeypatch.setattr(extractor, "_llm_extract", down)
    email_id = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    res = rerun(client, email_id)
    assert res.status_code == 502 and "not changed" in res.json()["detail"]


def test_rerun_is_rate_limited_per_email_and_overall(api, monkeypatch):
    _, _, client, _ = api
    import src.extractor as extractor
    monkeypatch.setattr(extractor, "_llm_extract", lambda text, model=None: {})
    a = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    b = send(client, atts=[attach("SI.txt", SI), attach("BL.txt", BL)])
    assert rerun(client, a).status_code == 200
    again = rerun(client, a)
    assert again.status_code == 429 and "just re-run" in again.json()["detail"]
    monkeypatch.setenv("RERUN_MAX_PER_HOUR", "1")
    limited = rerun(client, b)
    assert limited.status_code == 429 and "per hour" in limited.json()["detail"]


def test_rerun_of_something_unknown_is_a_404(api):
    _, _, client, _ = api
    assert rerun(client, "email_999").status_code == 404
