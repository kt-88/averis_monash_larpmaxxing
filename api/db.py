"""Storage: SQLite locally, Postgres when DATABASE_URL is set (Neon, Supabase, Render...)."""
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa

from src import learning

ROOT = Path(__file__).resolve().parent.parent


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        (ROOT / "output").mkdir(exist_ok=True)
        return f"sqlite:///{(ROOT / 'output' / 'app.db').as_posix()}"
    # Hosts hand out postgres:// or postgresql:// - name the pure-Python driver (pg8000: no native
    # libpq, so it also works where Windows blocks compiled DLLs).
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+pg8000://" + url[len(prefix):]
    # pg8000 has no sslmode/channel_binding URL options; SSL is switched on in make_engine().
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("sslmode", "channel_binding")]
    return urlunsplit(parts._replace(query=urlencode(query)))


def make_engine() -> sa.Engine:
    url = database_url()
    connect_args = {} if url.startswith("sqlite") else {"ssl_context": True}
    return sa.create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = make_engine()
meta = sa.MetaData()

# One row per processed email. `entry` is the submission entry; `detail` holds the extracted
# SI/BL fields and readable text for comparison emails (NULL until computed).
results = sa.Table(
    "results", meta,
    sa.Column("email_id", sa.String(64), primary_key=True),
    sa.Column("entry", sa.JSON, nullable=False),
    sa.Column("detail", sa.JSON, nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    # Fields a learned reviewer rule excused for this email (kept out of `detail` so the list stays light).
    sa.Column("learned_fields", sa.JSON, nullable=True),
)

# Human confirm/correct decisions, kept apart from the automatic result so neither overwrites the other.
decisions = sa.Table(
    "decisions", meta,
    sa.Column("email_id", sa.String(64), primary_key=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("defect_fields", sa.JSON, nullable=False),
    sa.Column("note", sa.Text, nullable=False, default=""),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    # Why the reviewer decided this, and (for blank_acceptable) which blank SI fields they accepted.
    sa.Column("reason", sa.String(32), nullable=True),
    sa.Column("accepted_blanks", sa.JSON, nullable=True),
)

# Columns added after the first deploy: create_all() never alters an existing table, so add them here.
_ADDED_COLUMNS = {
    "decisions": {"reason": "VARCHAR(32)", "accepted_blanks": "JSON"},
    "results": {"learned_fields": "JSON"},
}


def init_db() -> None:
    meta.create_all(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            have = {c["name"] for c in sa.inspect(conn).get_columns(table)}
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upsert(conn, table, key: str, values: dict) -> None:
    exists = conn.execute(sa.select(table.c[key]).where(table.c[key] == values[key])).first()
    if exists:
        conn.execute(table.update().where(table.c[key] == values[key]).values(**values))
    else:
        conn.execute(table.insert().values(**values))


def save_result(email_id: str, entry: dict, detail: dict | None = None, keep_detail: bool = True) -> None:
    """Insert/replace an email's result. Without new detail, an existing stored detail is kept
    unless keep_detail is False (used when a retry changes the email's outcome)."""
    with engine.begin() as conn:
        values = {"email_id": email_id, "entry": entry, "updated_at": _now()}
        if detail is not None or not keep_detail:
            values["detail"] = detail
            values["learned_fields"] = (detail or {}).get("learned_exceptions") or []
        _upsert(conn, results, "email_id", values)


def save_detail(email_id: str, detail: dict) -> None:
    with engine.begin() as conn:
        conn.execute(results.update().where(results.c.email_id == email_id)
                     .values(detail=detail, learned_fields=detail.get("learned_exceptions") or []))


def all_learned() -> dict[str, list[str]]:
    """{email_id: fields} for emails a learned reviewer rule helped resolve."""
    with engine.connect() as conn:
        rows = conn.execute(sa.select(results.c.email_id, results.c.learned_fields))
        return {r.email_id: r.learned_fields for r in rows if r.learned_fields}


def get_result(email_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(sa.select(results).where(results.c.email_id == email_id)).mappings().first()
    return dict(row) if row else None


def all_entries() -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(results.c.email_id, results.c.entry).order_by(results.c.email_id))
        return {r.email_id: r.entry for r in rows}


def count_results() -> int:
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(results)).scalar_one()


def save_decision(email_id: str, status: str, defect_fields: list[str], note: str,
                  reason: str | None = None, accepted_blanks: list[str] | None = None) -> None:
    with engine.begin() as conn:
        _upsert(conn, decisions, "email_id", {
            "email_id": email_id, "status": status, "defect_fields": defect_fields,
            "note": note, "decided_at": _now(), "reason": reason,
            "accepted_blanks": accepted_blanks or [],
        })


def all_decisions() -> dict[str, dict]:
    with engine.connect() as conn:
        return {r.email_id: {"status": r.status, "defect_fields": r.defect_fields, "note": r.note,
                             "reason": r.reason, "accepted_blanks": r.accepted_blanks or []}
                for r in conn.execute(sa.select(decisions))}


def learned_blanks() -> set[str]:
    """Fields whose blank SI value reviewers have accepted often enough to stop escalating."""
    return learning.learned_blank_fields(all_decisions())
