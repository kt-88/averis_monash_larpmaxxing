"""Local inbox loader: reads email records + attachment text from a data directory.

Expects <source>/emails.json (a list of {"email_id", "subject", "body",
"attachments"} records, where "attachments" is a list of filenames) and the
attachment files themselves under <source>/attachments/.
"""
import json
from pathlib import Path


class Inbox:
    def __init__(self, source: str):
        self.root = Path(source)
        self._emails = json.loads((self.root / "emails.json").read_text())

    def __iter__(self):
        return iter(self._emails)

    def read_text(self, path: str) -> str:
        return (self.root / "attachments" / path).read_text()

    def submit(self, output_dict: dict) -> None:
        print(f"[loader] submit() stub - {len(output_dict)} entries ready (not actually sent anywhere).")
