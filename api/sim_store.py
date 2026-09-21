"""Storage for emails composed in the simulator.

They live in the database, not on disk, so they survive restarts on hosts with a temporary disk (Render).
The tables are created on first use, against whichever database api.db is currently using.
"""
import re
from datetime import datetime, timezone

import sqlalchemy as sa

PREFIX = "sim/"     # attachment paths of simulated emails start with this, so the inbox knows where to read them
_meta = sa.MetaData()

sim_emails = sa.Table(
    "sim_emails", _meta,
    sa.Column("email_id", sa.String(64), primary_key=True),
    sa.Column("sender", sa.String(320), nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("body", sa.Text, nullable=False),
    sa.Column("attachments", sa.JSON, nullable=False),     # stored paths, in the order they were attached
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sim_files = sa.Table(
    "sim_files", _meta,
    sa.Column("path", sa.String(300), primary_key=True),
    sa.Column("data", sa.LargeBinary, nullable=False),
)

_ready: set[int] = set()


def _db():
    from api import db   # looked up on every call, so a reloaded api.db (tests) is always the one in use
    return db


def _engine() -> sa.Engine:
    engine = _db().engine
    if id(engine) not in _ready:
        _meta.create_all(engine)
        _ready.add(id(engine))
    return engine


def is_simulated(email_id: str) -> bool:
    return email_id.startswith("sim_")


def _as_email(row) -> dict:
    return {"email_id": row.email_id, "from": row.sender, "subject": row.subject, "body": row.body,
            "attachments": list(row.attachments or [])}


def count() -> int:
    with _engine().connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(sim_emails)).scalar_one()


def all_emails() -> list[dict]:
    with _engine().connect() as conn:
        return [_as_email(r) for r in conn.execute(sa.select(sim_emails).order_by(sim_emails.c.email_id))]


def get_email(email_id: str) -> dict | None:
    with _engine().connect() as conn:
        row = conn.execute(sa.select(sim_emails).where(sim_emails.c.email_id == email_id)).first()
    return _as_email(row) if row else None


def read_file(path: str) -> bytes | None:
    with _engine().connect() as conn:
        row = conn.execute(sa.select(sim_files.c.data).where(sim_files.c.path == path)).first()
    return bytes(row[0]) if row else None


def _next_number(conn) -> int:
    ids = [r[0] for r in conn.execute(sa.select(sim_emails.c.email_id))]
    numbers = [int(m.group(1)) for i in ids if (m := re.fullmatch(r"sim_(\d+)", i))]
    return max(numbers, default=0) + 1


def add_email(sender: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> dict:
    """Store a composed email and its attachments; returns it in the same shape the provided inbox uses."""
    for _ in range(5):   # two people composing at the same instant would pick the same number: try again
        try:
            with _engine().begin() as conn:
                email_id = f"sim_{_next_number(conn):04d}"
                paths = [f"{PREFIX}{email_id}/{n}_{name}" for n, (name, _) in enumerate(files, 1)]
                conn.execute(sim_emails.insert().values(
                    email_id=email_id, sender=sender, subject=subject, body=body, attachments=paths,
                    created_at=datetime.now(timezone.utc)))
                for path, (_, data) in zip(paths, files):
                    conn.execute(sim_files.insert().values(path=path, data=data))
            return {"email_id": email_id, "from": sender, "subject": subject, "body": body, "attachments": paths}
        except sa.exc.IntegrityError:
            continue
    raise RuntimeError("could not allocate an id for the simulated email")


def delete_email(email_id: str) -> bool:
    """Remove a simulated email, its files, its processed result and any human decision about it."""
    db = _db()
    with _engine().begin() as conn:
        row = conn.execute(sa.select(sim_emails).where(sim_emails.c.email_id == email_id)).first()
        if row is None:
            return False
        paths = list(row.attachments or [])
        if paths:
            conn.execute(sim_files.delete().where(sim_files.c.path.in_(paths)))
        conn.execute(sim_emails.delete().where(sim_emails.c.email_id == email_id))
        conn.execute(db.results.delete().where(db.results.c.email_id == email_id))
        conn.execute(db.decisions.delete().where(db.decisions.c.email_id == email_id))
    return True
