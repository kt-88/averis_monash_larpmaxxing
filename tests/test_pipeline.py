import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from loader import Inbox  # noqa: E402
from src.classifier import CATEGORIES  # noqa: E402
from src.comparator import compare_fields  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402
from src.report import REVIEW_REASONS, STATUSES  # noqa: E402

KEYS = {"category", "status", "review_reason", "defect_fields", "has_defect"}


def test_comparator_is_deterministic():
    a = {"shipper": "A CO", "consignee": "B", "notify_party": "B", "port_of_loading": "NANTONG, CHINA (CNNTG)",
         "port_of_discharge": "KARACHI", "container_count": 6, "gross_weight_kg": 131058}
    b = {**a, "port_of_loading": "NANTONG, CHINA", "consignee": "C"}
    assert compare_fields(a, b) == ("MISMATCH", ["consignee"])
    assert compare_fields(a, a) == ("OK", [])


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
def test_pipeline_output_shape():
    submission = run_pipeline(Inbox(str(ROOT / "data")), limit=6, workers=2)
    assert len(submission) == 6
    for entry in submission.values():
        assert set(entry) == KEYS
        assert entry["category"] in CATEGORIES
        assert entry["status"] in STATUSES
        assert entry["review_reason"] is None or entry["review_reason"] in REVIEW_REASONS
        assert isinstance(entry["defect_fields"], list) and isinstance(entry["has_defect"], bool)
