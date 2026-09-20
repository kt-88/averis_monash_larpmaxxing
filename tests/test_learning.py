import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.comparator import compare_fields  # noqa: E402
from src.escalation import check_missing_values, excusable_blanks  # noqa: E402
from src.extractor import BLANK, FIELDS  # noqa: E402
from src.learning import MIN_VOTES, blank_votes, learned_blank_fields  # noqa: E402

FULL = {"shipper": "A CO", "consignee": "B CO", "notify_party": "B CO", "port_of_loading": "NANTONG",
        "port_of_discharge": "KARACHI", "container_count": 6, "gross_weight_kg": 131058}


def decision(reason, blanks):
    return {"reason": reason, "accepted_blanks": blanks}


def test_rule_needs_enough_agreeing_decisions():
    one = {"e1": decision("blank_acceptable", ["gross_weight_kg"])}
    assert learned_blank_fields(one) == set()
    two = {**one, "e2": decision("blank_acceptable", ["gross_weight_kg", "port_of_discharge"])}
    assert MIN_VOTES == 2
    assert learned_blank_fields(two) == {"gross_weight_kg"}
    assert blank_votes(two)["port_of_discharge"] == 1


def test_other_reasons_teach_nothing():
    d = {f"e{i}": decision("genuine_issue", ["gross_weight_kg"]) for i in range(5)}
    assert learned_blank_fields(d) == set()


def test_blank_si_with_bl_value_is_excused_only_when_learned():
    si = {**FULL, "gross_weight_kg": None}
    assert excusable_blanks(si, FULL, set()) == []
    assert excusable_blanks(si, FULL, {"gross_weight_kg"}) == ["gross_weight_kg"]
    assert check_missing_values(si, FULL) == "missing_value"
    assert check_missing_values(si, FULL, {"gross_weight_kg"}) is None
    assert check_missing_values(si, FULL, {"port_of_discharge"}) == "missing_value"   # rule for another field


def test_a_blank_bl_is_never_excused():
    bl = {**FULL, "gross_weight_kg": BLANK}
    assert excusable_blanks(FULL, bl, set(FIELDS)) == []
    assert check_missing_values(FULL, bl, set(FIELDS)) == "missing_value"
    both = {**FULL, "gross_weight_kg": None}
    assert excusable_blanks(both, bl, set(FIELDS)) == []   # blank on both sides: still needs a person


def test_excused_field_is_skipped_but_others_still_compared():
    si = {**FULL, "gross_weight_kg": None}
    assert compare_fields(si, FULL, skip=["gross_weight_kg"]) == ("OK", [])
    assert compare_fields({**si, "consignee": "OTHER"}, FULL, skip=["gross_weight_kg"]) == ("MISMATCH", ["consignee"])
