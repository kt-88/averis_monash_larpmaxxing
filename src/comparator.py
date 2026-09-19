"""Deterministic comparison of SI fields against BL fields. No AI here."""
from src.extractor import FIELD_KEYS

NO_MISMATCH = "No mismatch detected"


def compare_fields(si_fields: dict, bl_fields: dict):
    """Compare the 7 extracted fields. Returns NO_MISMATCH or a list of
    {"field", "si_value", "bl_value"} dicts for each differing field.

    STUB: uses exact equality; no normalization/fuzzy matching yet.
    """
    mismatches = []
    for key in FIELD_KEYS:
        si_value = si_fields.get(key)
        bl_value = bl_fields.get(key)
        if si_value != bl_value:
            mismatches.append({
                "field": key,
                "si_value": si_value,
                "bl_value": bl_value,
            })

    if not mismatches:
        return NO_MISMATCH
    return mismatches
