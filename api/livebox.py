"""An inbox that holds both the provided emails and the ones composed in the simulator.

It wraps the provided loader.Inbox (which is left untouched) and answers the same questions the pipeline asks:
iterate the emails, get one by id, read an attachment.
"""
from api import sim_store


class LiveInbox:
    def __init__(self, base):
        self.base = base

    def __iter__(self):
        yield from self.base
        yield from sim_store.all_emails()

    def get(self, email_id: str) -> dict:
        try:
            return self.base.get(email_id)
        except KeyError:
            email = sim_store.get_email(email_id)
            if email is None:
                raise
            return email

    def read_bytes(self, path: str) -> bytes:
        if path.startswith(sim_store.PREFIX):
            data = sim_store.read_file(path)
            if data is None:
                raise FileNotFoundError(path)
            return data
        return self.base.read_bytes(path)

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding, errors="replace")

    def __getattr__(self, name):   # anything else (sample_submission, submit, root...) is the provided inbox's
        return getattr(self.base, name)
