"""Stage 3: deterministic comparison of SI vs BL fields (no LLM)."""
import re

from src.extractor import FIELDS

PORT_FIELDS = {"port_of_loading", "port_of_discharge"}
NUMERIC_FIELDS = {"container_count", "gross_weight_kg"}


def _clean(s) -> str:
    s = re.sub(r"\([^)]*\)", " ", str(s).upper())
    s = re.sub(r"[^A-Z0-9 ,]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,")


def normalize_number(v):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def names_match(a, b) -> bool:
    return _clean(a) == _clean(b)


def ports_match(a, b) -> bool:
    ca, cb = _clean(a), _clean(b)
    if ca == cb:
        return True
    # "NANTONG" vs "NANTONG, CHINA": same city, one side omits the country
    city_a, *rest_a = ca.split(",")
    city_b, *rest_b = cb.split(",")
    return city_a.strip() == city_b.strip() and (not rest_a or not rest_b)


def numbers_match(a, b) -> bool:
    na, nb = normalize_number(a), normalize_number(b)
    return na is not None and na == nb


def field_matches(field: str, a, b) -> bool:
    if field in NUMERIC_FIELDS:
        return numbers_match(a, b)
    if field in PORT_FIELDS:
        return ports_match(a, b)
    return names_match(a, b)


def compare_fields(si: dict, bl: dict) -> tuple[str, list[str]]:
    """Return (status, defect_fields). Callers must have ruled out missing values first."""
    diffs = [f for f in FIELDS if not field_matches(f, si.get(f), bl.get(f))]
    return ("MISMATCH", diffs) if diffs else ("OK", [])
