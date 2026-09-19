"""Entry point: load the inbox, run the pipeline, write output/submission.json."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from loader import Inbox
from src.pipeline import run_pipeline

OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "submission.json"


def main():
    load_dotenv()
    source = os.environ.get("INBOX_SOURCE", "data")
    inbox = Inbox(source)

    output = run_pipeline(inbox)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"Wrote {len(output)} entries to {OUTPUT_PATH}")

    inbox.submit(output)


if __name__ == "__main__":
    main()
