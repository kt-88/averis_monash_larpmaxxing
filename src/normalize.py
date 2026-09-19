"""Turn raw extracted strings into comparable values (cosmetic clean-up only)."""
import re

_PLACEHOLDER = re.compile(
    r"^[\s_\-?.*]*$|^(tba|tbc|tbd|n/?a|nil|none|blank|to be (advised|confirmed))\b", re.I)


def is_blank(v) -> bool:
    return v is None or bool(_PLACEHOLDER.match(str(v).strip()))


def normalize_company(v: str) -> str:
    s = re.split(r"\s*\|\s*", v)[0]                                  # drop address lines
    s = re.split(r"\s+on behalf of\s+", s, flags=re.I)[0]
    s = re.sub(r"[\s,;]+(t|tel|phone)[.:]?\s*[\d+()\- ]{6,}$", "", s, flags=re.I)  # trailing phone
    return re.sub(r"\s+", " ", s).strip(" ,;.").upper()


def normalize_weight_kg(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(kgs?|kilograms?|mt|tonnes?|tons?)?", str(v), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return n * 1000 if unit in ("mt", "tonne", "tonnes", "ton", "tons") else n


def normalize_container_count(v) -> int | None:
    if isinstance(v, (int, float)):
        return int(v)
    pairs = re.findall(r"(\d+)\s*[x×]\s*\d{2}", str(v), re.I)        # "2 x 20' + 1 x 40'" -> 3
    if pairs:
        return sum(int(n) for n in pairs)
    m = re.match(r"\s*(\d+)\b", str(v))
    return int(m.group(1)) if m else None


def normalize_port(v: str) -> str:
    s = re.sub(r"\(\s*[A-Z]{5}\s*\)", "", v.upper())                 # (CNNTG) UN/LOCODE
    s = re.sub(r",\s*[A-Z .]+$", "", s.strip())                      # ", CHINA" country suffix
    return re.sub(r"\s+", " ", s).strip(" ,")


def normalize(field: str, v):
    """Return the comparable value, or None if the value is blank/unparseable."""
    if is_blank(v):
        return None
    fn = {"gross_weight_kg": normalize_weight_kg, "container_count": normalize_container_count,
          "port_of_loading": normalize_port, "port_of_discharge": normalize_port}.get(field, normalize_company)
    return fn(v)
