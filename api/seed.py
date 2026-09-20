"""Load existing results into the database.

    python -m api.seed                      import output/submission.json (+ review_decisions.json)
    python -m api.seed --details            also compute SI/BL details for comparison emails
    python -m api.seed --details --max-calls 0   details from the local LLM cache only (no API calls)

Point it at Postgres by setting DATABASE_URL first - the same script then fills Neon/Supabase.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from api import db  # noqa: E402
from loader import Inbox  # noqa: E402
from src.cache import BudgetExceeded, set_call_budget  # noqa: E402
from src.pipeline import analyze_comparison  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="data")
    p.add_argument("--submission", default=str(ROOT / "output" / "submission.json"))
    p.add_argument("--details", action="store_true", help="compute and store SI/BL details")
    p.add_argument("--max-calls", type=int, default=None, help="cap on real Gemini calls (0 = cache only)")
    args = p.parse_args()

    db.init_db()
    submission = json.loads(Path(args.submission).read_text(encoding="utf-8"))
    for email_id, entry in submission.items():
        db.save_result(email_id, entry)
    print(f"imported {len(submission)} results")

    decisions_path = ROOT / "output" / "review_decisions.json"
    if decisions_path.exists():
        for email_id, d in json.loads(decisions_path.read_text(encoding="utf-8")).items():
            db.save_decision(email_id, d["status"], d.get("defect_fields", []), d.get("note", ""))
        print("imported review decisions")

    if not args.details:
        return
    set_call_budget(args.max_calls)
    inbox = Inbox(args.source if Path(args.source).is_absolute() else str(ROOT / args.source))
    todo = [e for e, v in submission.items() if v["category"] == "BL_COMPARISON"
            and (db.get_result(e) or {}).get("detail") is None]
    done = skipped = 0
    for email_id in todo:
        try:
            d = analyze_comparison(inbox, inbox.get(email_id))
        except BudgetExceeded:
            skipped += 1
            continue
        except Exception as err:
            print(f"  {email_id}: {err!r}")
            skipped += 1
            continue
        db.save_detail(email_id, {k: v for k, v in d.items() if k != "entry"})
        done += 1
    print(f"details stored for {done} emails, {skipped} skipped (not cached / no API budget)")


if __name__ == "__main__":
    main()
