"""Tests for the reading + extraction stage. None of these call the real API."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import docx
import openpyxl
import pytest
from PIL import Image

import src.extractor as extractor
import src.readers as readers
from src.cache import BudgetExceeded
from src.extractor import FIELDS, build_field, extract_fields, extract_fields_detailed, flat_values
from src.labels import parse_line
from src.normalize import is_blank, normalize
from src.pipeline import analyze_comparison
from src.readers import ScannedDocument, UnreadableAttachment, read_attachment, row_to_line

DATA = ROOT / "data" / "attachments"

SI_TEXT = """SHIPPING INSTRUCTION
Shipper: ACME TRADING LTD
    1 HARBOUR ROAD; SINGAPORE
Consignee: BETA CO
Notify Party: BETA CO
Port of Loading: SHANGHAI, CHINA (CNSHA)
Port of Discharge: KARACHI, PAKISTAN
Container Count: 2 x 20'GP
Gross Weight (KG): 20,000 KG
"""


@pytest.fixture(autouse=True)
def no_api(monkeypatch):
    """Any accidental LLM call fails the test instead of spending money."""
    def boom(*a, **k):
        raise AssertionError("test tried to call the real LLM")
    monkeypatch.setattr(extractor, "llm_json_text", boom)
    monkeypatch.setattr(readers, "llm_vision_text", boom)


# ---------- normalize ----------
@pytest.mark.parametrize("field,raw,expected", [
    ("gross_weight_kg", "131,058 KG", 131058.0),
    ("gross_weight_kg", "1.5 MT", 1500.0),
    ("gross_weight_kg", 341715, 341715.0),
    ("container_count", "3X20'FCL", 3),
    ("container_count", "6 x 40'HC", 6),
    ("container_count", "2 x 20' + 1 x 40'", 3),
    ("port_of_loading", "NANTONG, CHINA (CNNTG)", "NANTONG"),
    ("port_of_discharge", "SINGAPORE", "SINGAPORE"),
    ("shipper", "APRIL FINE PAPER TRADING | ON BEHALF OF VITAL SOLUTIONS PTE LTD | 77 ROBINSON ROAD",
     "APRIL FINE PAPER TRADING"),
    ("consignee", "moorim sp co., ltd", "MOORIM SP CO., LTD"),
])
def test_normalize(field, raw, expected):
    assert normalize(field, raw) == expected


@pytest.mark.parametrize("v", ["???", "____", "TBA", "N/A", "-", "", "  ", None, "To be advised"])
def test_placeholders_are_blank(v):
    assert is_blank(v) and normalize("consignee", v) is None


# ---------- labels ----------
@pytest.mark.parametrize("line,field", [
    ("Port of Loading: X", "port_of_loading"), ("Load Port: X", "port_of_loading"), ("POL X", "port_of_loading"),
    ("Discharge Port: X", "port_of_discharge"), ("POD: X", "port_of_discharge"),
    ("CONSIGNEE: X", "consignee"), ("To the Order of: X", "consignee"),
    ("Consignee (Non-Negotiable) X", "consignee"), ("Notify Party X", "notify_party"),
    ("Notify Party/Intermediate Consignee: X", "notify_party"),
    ("Shipper/Exporter: X", "shipper"), ("Shipper (Principal or Seller) (\u53d1\u8d27\u4eba): X", "shipper"),
    ("Gross Weight (KG): 1", "gross_weight_kg"), ("Gross Wt (kgs): 1", "gross_weight_kg"),
    ("TOTAL Gross Weightnn(KGS): 1", "gross_weight_kg"),
    ("No. of Containers or Packages: 1 x 40'HC", "container_count"), ("Containers: 6 x 40'HC", "container_count"),
])
def test_label_variants_map_to_canonical_names(line, field):
    assert parse_line(line)[0] == field


@pytest.mark.parametrize("line", ["Vessel Name: X", "HS Code: 4802", "Container No.: ABCU1234567",
                                  "CONTAINER NO. DESCRIPTION GROSS WEIGHT (KG)", "Booking Ref: 1"])
def test_unrelated_lines_do_not_match(line):
    assert parse_line(line) is None


# ---------- extraction ----------
def test_extracts_all_seven_fields_with_normalized_values():
    assert extract_fields(SI_TEXT) == {
        "shipper": "ACME TRADING LTD", "consignee": "BETA CO", "notify_party": "BETA CO",
        "port_of_loading": "SHANGHAI", "port_of_discharge": "KARACHI",
        "container_count": 2, "gross_weight_kg": 20000.0}


def test_each_field_has_the_five_keys():
    d = extract_fields_detailed(SI_TEXT)
    assert list(d) == FIELDS
    for v in d.values():
        assert set(v) == {"value", "normalized", "confidence", "snippet", "label_found", "llm", "agree"}
        assert 0.0 <= v["confidence"] <= 1.0


@pytest.mark.parametrize("placeholder", ["???", "TBA", "____", "N/A", ""])
def test_blank_value_is_null_but_label_found(placeholder):
    d = extract_fields_detailed(SI_TEXT.replace("Consignee: BETA CO", f"Consignee: {placeholder}"))
    assert d["consignee"]["normalized"] is None and d["consignee"]["value"] is None
    assert d["consignee"]["label_found"] is True          # blank, not absent
    assert d["notify_party"]["normalized"] == "BETA CO"    # never copied into the blank field


def test_absent_label_is_null_and_label_not_found():
    # No LLM in tests: the autouse fixture makes the LLM raise, and extraction falls back to regex only.
    d = extract_fields_detailed(SI_TEXT.replace("Notify Party: BETA CO\n", ""))
    assert d["notify_party"]["normalized"] is None and d["notify_party"]["label_found"] is False


def test_llm_is_not_called_when_regex_settles_everything(monkeypatch):
    monkeypatch.setattr(extractor, "llm_json_text", lambda *a: pytest.fail("LLM was called"))
    extract_fields_detailed(SI_TEXT)


def test_flat_values_keeps_the_old_shape():
    flat = flat_values(extract_fields_detailed(SI_TEXT))
    assert list(flat) == FIELDS and flat["container_count"] == 2


# ---------- confidence ----------
def test_confidence_regex_only_is_high_but_not_perfect():
    d = extract_fields_detailed(SI_TEXT)
    assert d["shipper"]["confidence"] == 0.85


def test_confidence_full_when_regex_and_llm_agree():
    rx = extractor.regex_extract(SI_TEXT)["shipper"]
    f = build_field("shipper", SI_TEXT, rx, llm=("ACME TRADING LTD", "Shipper: ACME TRADING LTD"))
    assert f["confidence"] == 1.0


def test_confidence_drops_when_regex_and_llm_disagree():
    rx = extractor.regex_extract(SI_TEXT)["shipper"]
    f = build_field("shipper", SI_TEXT, rx, llm=("OTHER CO", "Shipper: ACME TRADING LTD"))
    assert f["confidence"] <= 0.4 and f["normalized"] == "ACME TRADING LTD"


def test_llm_value_with_invented_snippet_is_rejected():
    f = build_field("port_of_loading", "Port: nowhere", None, llm=("NINGBO", "Load Port: NINGBO"))
    assert f["normalized"] is None and f["confidence"] <= 0.2


def test_llm_value_with_real_snippet_is_accepted():
    text = "Origin Port: SHANGHAI, CHINA"
    f = build_field("port_of_loading", text, None, llm=("SHANGHAI, CHINA", "Origin Port: SHANGHAI, CHINA"))
    assert f["normalized"] == "SHANGHAI" and f["confidence"] >= 0.8


def test_insane_value_gets_lower_confidence():
    f = build_field("gross_weight_kg", "Gross Weight: 99999999",
                    {"raw": "99999999", "snippet": "Gross Weight: 99999999"})
    assert f["confidence"] < 0.85


def test_llm_failure_falls_back_to_regex(monkeypatch):
    def fail(*a):
        raise RuntimeError("503")
    monkeypatch.setattr(extractor, "llm_json_text", fail)
    text = SI_TEXT.replace("Port of Loading", "Origin Port")            # regex misses -> LLM asked -> fails
    d = extract_fields_detailed(text)
    assert d["port_of_loading"]["normalized"] is None and d["shipper"]["normalized"] == "ACME TRADING LTD"


def test_budget_error_is_not_swallowed(monkeypatch):
    def cap(*a):
        raise BudgetExceeded("cap")
    monkeypatch.setattr(extractor, "llm_json_text", cap)
    with pytest.raises(BudgetExceeded):
        extract_fields_detailed(SI_TEXT.replace("Port of Loading", "Origin Port"))


# ---------- readers ----------
def test_row_to_line():
    assert row_to_line(["Consignee", "ACME LTD"]) == "Consignee: ACME LTD"
    assert row_to_line(["Consignee", None]) == "Consignee:"
    assert row_to_line([None, None]) is None
    assert row_to_line(["Shipper", "ACME\n1 ROAD"]) == "Shipper: ACME | 1 ROAD"


def test_txt_reader_handles_bom():
    assert read_attachment("a.txt", b"\xef\xbb\xbfShipper: X").startswith("Shipper")


def test_zero_byte_file_raises_unreadable():
    for name in ("a.txt", "a.pdf", "a.docx", "a.xlsx"):
        with pytest.raises(UnreadableAttachment, match="empty"):
            read_attachment(name, b"")


@pytest.mark.parametrize("name,data", [
    ("a.pdf", b"%PDF-1.4 garbage"), ("a.pdf", b"not a pdf at all"),
    ("a.docx", b"not a zip"), ("a.xlsx", b"not a zip"),
    ("a.txt", b"\x00\x01\x02\x03\x04" * 50),
])
def test_corrupt_files_raise_unreadable_not_crash(name, data):
    with pytest.raises(UnreadableAttachment):
        read_attachment(name, data)


def test_unsupported_extension():
    with pytest.raises(UnreadableAttachment, match="unsupported"):
        read_attachment("a.png", b"abc")


def test_xlsx_label_value_rows_and_blank_value():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ACME TITLE", None])
    ws.append(["Consignee", "BETA CO | 1 ROAD"])
    ws.append(["Notify Party", None])
    ws.append(["Gross Weight (KG)", 341715])
    buf = io.BytesIO()
    wb.save(buf)
    text = read_attachment("a.xlsx", buf.getvalue())
    assert "Consignee: BETA CO | 1 ROAD" in text and "Notify Party:" in text
    assert "Gross Weight (KG): 341715" in text
    d = extract_fields_detailed(text)
    assert d["consignee"]["normalized"] == "BETA CO" and d["gross_weight_kg"]["normalized"] == 341715.0
    assert d["notify_party"]["normalized"] is None and d["notify_party"]["label_found"] is True


def test_docx_paragraphs_and_table_in_order():
    d = docx.Document()
    d.add_paragraph("BILL OF LADING (DRAFT)")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Shipper (Principal or Seller) (\u53d1\u8d27\u4eba)"
    t.cell(0, 1).text = "ACME\nON BEHALF OF X\n1 ROAD"
    t.cell(1, 0).text = "Gross Wt (kgs) (\u6bdb\u91cd KGS)"
    t.cell(1, 1).text = "243,588"
    buf = io.BytesIO()
    d.save(buf)
    text = read_attachment("a.docx", buf.getvalue())
    assert text.startswith("BILL OF LADING")
    flat = extract_fields(text)
    assert flat["shipper"] == "ACME" and flat["gross_weight_kg"] == 243588.0


# ---------- scanned PDFs (a PDF that is only a picture) ----------
def _scanned_pdf() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(buf, "PDF")
    return buf.getvalue()


def test_a_scanned_pdf_is_escalated_but_the_reviewer_gets_a_transcript(monkeypatch):
    seen = {}

    def fake(prompt, pages):
        seen["pages"] = pages
        return "SHIPPING INSTRUCTION\nShipper: ACME LTD\nContainers: 6 x 40'HC\n"
    monkeypatch.setattr(readers, "llm_vision_text", fake)
    with pytest.raises(ScannedDocument, match="scanned image") as e:
        read_attachment("scan.pdf", _scanned_pdf())
    assert seen["pages"][0][:4] == b"\x89PNG"                      # the pages went to the vision model
    assert "Transcribed from a scanned image" in e.value.text and "Shipper: ACME LTD" in e.value.text


def test_a_scanned_pdf_is_an_unreadable_attachment_so_it_maps_to_the_unreadable_reason():
    assert issubclass(ScannedDocument, UnreadableAttachment)


def test_a_scanned_pdf_is_escalated_even_if_the_vision_model_fails(monkeypatch):
    def fail(prompt, pages):
        raise RuntimeError("model 404")
    monkeypatch.setattr(readers, "llm_vision_text", fail)
    with pytest.raises(ScannedDocument) as e:
        read_attachment("scan.pdf", _scanned_pdf())
    assert e.value.text == ""                                     # no transcript, but still escalated


def test_a_scanned_pdf_is_escalated_even_when_the_call_budget_is_used_up(monkeypatch):
    def cap(prompt, pages):
        raise BudgetExceeded("cap")
    monkeypatch.setattr(readers, "llm_vision_text", cap)
    with pytest.raises(ScannedDocument):                          # the decision does not need the transcript
        read_attachment("scan.pdf", _scanned_pdf())


class _Inbox:
    def __init__(self, files):
        self.files = files

    def read_bytes(self, path):
        return self.files[path]


def test_a_scanned_pair_goes_to_review_and_both_transcripts_are_kept(monkeypatch):
    monkeypatch.setattr(readers, "llm_vision_text", lambda prompt, pages: "Shipper: ACME LTD")
    inbox = _Inbox({"si.pdf": _scanned_pdf(), "bl.pdf": _scanned_pdf()})
    out = analyze_comparison(inbox, {"attachments": ["si.pdf", "bl.pdf"]})
    assert (out["entry"]["status"], out["entry"]["review_reason"]) == ("NEEDS_REVIEW", "unreadable")
    assert "Shipper: ACME LTD" in out["si_text"] and "Shipper: ACME LTD" in out["bl_text"]   # the reviewer sees both


def test_one_scanned_document_still_shows_the_readable_one(monkeypatch):
    monkeypatch.setattr(readers, "llm_vision_text", lambda prompt, pages: "")
    inbox = _Inbox({"si.txt": SI_TEXT.encode(), "bl.pdf": _scanned_pdf()})
    out = analyze_comparison(inbox, {"attachments": ["si.txt", "bl.pdf"]})
    assert out["entry"]["review_reason"] == "unreadable"
    assert "Shipper: ACME TRADING LTD" in out["si_text"] and out["bl_text"] is None


# ---------- real sample files (read-only) ----------
def _read(name):
    p = DATA / name
    return read_attachment(str(p), p.read_bytes())


def test_real_txt_pdf_docx_xlsx_files():
    assert extract_fields(_read("email_001_SI.txt"))["gross_weight_kg"] == 21577.0
    assert extract_fields(_read("email_059_SI.pdf"))["container_count"] == 6
    assert extract_fields(_read("email_055_BL.docx"))["shipper"] == "APRIL FINE PAPER TRADING"
    assert extract_fields(_read("email_005_BL.xlsx"))["gross_weight_kg"] == 341715.0


def test_real_corrupt_pdfs_are_unreadable():
    for n in ("email_511_BL.pdf", "email_515_BL.pdf"):            # garbage after the header: no reader can open them
        with pytest.raises(UnreadableAttachment):
            _read(n)


def test_a_damaged_pdf_with_a_broken_index_is_repaired_and_read():
    text = _read("email_499_BL.pdf")                              # pdfminer refuses it; PDFium repairs it
    assert text.startswith("BILL OF LADING (DRAFT)")
    assert extract_fields(text)["gross_weight_kg"] == 41326.0
    assert extract_fields(_read("email_499_SI.pdf"))["gross_weight_kg"] == 40326.0   # a real difference, now findable


@pytest.mark.parametrize("email", ["email_208", "email_351", "email_407"])
def test_an_overlapping_label_and_value_are_read_in_order(email):
    si, bl = _read(f"{email}_SI.pdf"), _read(f"{email}_BL.pdf")
    assert "Notify Party/Intermediate Consignee " in si + bl      # the long label is intact, not shuffled letter by letter
    party = extract_fields(si)["notify_party"]
    assert party and party == extract_fields(bl)["notify_party"]  # so both sides now name the same notify party


def test_the_real_scanned_sample_pdfs_are_escalated_not_trusted(monkeypatch):
    monkeypatch.setattr(readers, "llm_vision_text", lambda prompt, pages: "Shipper: ACME LTD")   # no real Gemini call
    for n in ("email_512", "email_513", "email_514"):
        for side in ("SI", "BL"):
            with pytest.raises(ScannedDocument):
                _read(f"{n}_{side}.pdf")


def test_real_blank_si_files_keep_blank_fields_null():
    d = extract_fields_detailed(_read("email_519_SI.txt"))
    assert d["shipper"]["normalized"] is None and d["shipper"]["label_found"] is True


# ---------- "re-run with Gemini": the cross-check and the fresh-call switch ----------
def test_agree_is_unset_when_the_llm_was_not_asked():
    d = extract_fields_detailed(SI_TEXT)
    assert all(v["agree"] is None and v["llm"] is None for v in d.values())


def test_agree_records_whether_the_llm_matched(monkeypatch):
    replies = {"shipper": ("ACME TRADING LTD", "Shipper: ACME TRADING LTD"),
               "consignee": ("SOMEONE ELSE", "Consignee: BETA CO")}
    monkeypatch.setattr(extractor, "_llm_extract", lambda text, model=None: replies)
    with extractor.cross_check_with_llm():
        d = extract_fields_detailed(SI_TEXT)
    assert d["shipper"]["agree"] is True and d["shipper"]["llm"] == "ACME TRADING LTD"
    assert d["consignee"]["agree"] is False and d["consignee"]["llm"] == "SOMEONE ELSE"
    assert d["consignee"]["normalized"] == "BETA CO"          # the value from the document still wins


def test_a_requested_cross_check_does_not_hide_an_llm_failure(monkeypatch):
    def down(text, model=None):
        raise RuntimeError("429 quota")
    monkeypatch.setattr(extractor, "_llm_extract", down)
    with pytest.raises(RuntimeError):
        with extractor.cross_check_with_llm():
            extract_fields_detailed(SI_TEXT)
    assert extract_fields_detailed(SI_TEXT)["shipper"]["normalized"] == "ACME TRADING LTD"   # normal runs still fall back


def test_fresh_llm_calls_ignore_the_saved_answer(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []
    fn = lambda: (calls.append(1) or f"answer {len(calls)}")
    assert cache.cached_llm_call("m", "prompt", fn) == "answer 1"
    assert cache.cached_llm_call("m", "prompt", fn) == "answer 1" and len(calls) == 1      # normally: saved answer
    with cache.fresh_llm_calls():
        assert cache.cached_llm_call("m", "prompt", fn) == "answer 2"                      # asked again
    assert cache.cached_llm_call("m", "prompt", fn) == "answer 2" and len(calls) == 2      # the new answer replaced the old
