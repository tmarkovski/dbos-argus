"""DBOS database adapter package.

`make_db()` picks an `ArgusDB` implementation from `settings.database_url`.
`db` is the eagerly-constructed singleton; `engine` is re-exported for the
small handful of call sites (CLI, schema-bootstrap script) that still use the
SQLAlchemy engine directly.
"""

from __future__ import annotations

from sqlalchemy.engine.url import make_url

from ..settings import settings
from .base import ArgusDB
from .postgres import PostgresArgusDB
from .sqlite import SqliteArgusDB


def make_db() -> ArgusDB:
    drivername = make_url(settings.database_url).drivername.split("+", 1)[0]
    if drivername in ("postgresql", "postgres"):
        return PostgresArgusDB(settings)
    if drivername == "sqlite":
        return SqliteArgusDB(settings)
    raise ValueError(f"Unsupported database driver: {drivername!r}. Supported: postgresql, sqlite.")


db: ArgusDB = make_db()
engine = db.engine

__all__ = ["ArgusDB", "PostgresArgusDB", "SqliteArgusDB", "db", "engine", "make_db"]
