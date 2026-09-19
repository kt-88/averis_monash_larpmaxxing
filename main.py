"""python main.py --limit 20 --out output/submission.json"""
import argparse
import os

from dotenv import load_dotenv

load_dotenv()

from loader import Inbox  # noqa: E402
from src.cache import set_call_budget  # noqa: E402
from src.pipeline import run_pipeline, save_submission  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Shipping document verification pipeline")
    p.add_argument("--source", default=os.environ.get("INBOX_SOURCE", "data"), help="data dir or http URL")
    p.add_argument("--limit", type=int, default=None, help="process only the first N emails")
    p.add_argument("--max-calls", type=int, default=None, help="hard cap on real API calls this run")
    p.add_argument("--out", default="output/submission.json")
    p.add_argument("--workers", type=int, default=int(os.environ.get("MAX_WORKERS", "4")))
    p.add_argument("--submit", action="store_true", help="POST to the scoring server (HTTP source only)")
    return p.parse_args()


def main():
    args = parse_args()
    set_call_budget(args.max_calls)
    inbox = Inbox(args.source)
    submission = run_pipeline(inbox, limit=args.limit, workers=args.workers)
    save_submission(submission, args.out)
    print(f"Wrote {len(submission)} entries to {args.out}")
    if args.submit:
        inbox.submit(submission)


if __name__ == "__main__":
    main()
