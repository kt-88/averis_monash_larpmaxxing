import re

_PATTERNS = {
    "shipper":           r"shipper(?:/exporter)?|exporter",
    "consignee":         r"consignee|to the order of|deliver to",
    "notify_party":      r"notify(?: party)?",
    "port_of_loading":   r"port of loading|load(?:ing)? port|pol",
    "port_of_discharge": r"port of discharge|discharge port|destination port|pod",
    "container_count":   r"no\.? of containers(?: or packages)?|total containers|container count|containers?(?=\s*:)",
    "gross_weight_kg":   r"(?:total )?gross (?:weight|wt)(?:nn)?",
}

_CJK = re.compile(r"[\u4e00-\u9fff]+")
# label, then any "(...)" groups, then an optional ":" or "-", then the value
_START = {f: re.compile(rf"\s*(?:{p})\b(?:\s*\([^)]*\))*\s*[:\-]?\s*(.*)", re.I)
          for f, p in _PATTERNS.items()}

def parse_line(line: str):
    """'Port of Discharge (POD) FREMANTLE' -> ('port_of_discharge', 'FREMANTLE'), else None."""
    text = _CJK.sub("", line)
    for field, rx in _START.items():
        m = rx.match(text)
        if m:
            return field, m.group(1).strip()
    return None
