"""Local inbox loader: reads email records + attachment bytes/text from a
data directory laid out as:

    <source>/inbox/email_XXX.json   one file per email:
        {"email_id", "from", "subject", "body", "attachments": [<path>, ...]}
    <source>/attachments/...        the SI/BL files themselves

Attachment paths in a record are given relative to <source> already
(e.g. "attachments/email_004_SI.txt") — read_text/read_bytes take them as-is.
"""
import json
from pathlib import Path


class Inbox:
    def __init__(self, source: str):
        self.root = Path(source)
        self._emails = [
            json.loads(p.read_text())
            for p in sorted((self.root / "inbox").glob("email_*.json"))
        ]

    def __iter__(self):
        return iter(self._emails)

    def get(self, email_id: str) -> dict:
        for email in self._emails:
            if email["email_id"] == email_id:
                return email
        raise KeyError(f"no such email: {email_id}")

    def read_bytes(self, path: str) -> bytes:
        return (self.root / path).read_bytes()

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding, errors="replace")

    def sample_submission(self) -> dict:
        return json.loads((self.root / "sample_submission.json").read_text())

    def submit(self, output_dict: dict) -> None:
        raise RuntimeError(
            "submit() needs the docker scoring server — this loader only reads "
            "a local folder. Run `docker compose up --build` and use "
            "Inbox('http://localhost:8080') to score a submission."
        )