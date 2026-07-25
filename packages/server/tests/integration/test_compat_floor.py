"""Exact-floor verification for the Postgres compatibility floor.

`tests/test_compat.py` proves the *SQLite* floor exactly by replaying DBOS'
SQLite migrations in memory. Postgres DDL needs a live server, so the equivalent
proof lives here and runs on the `postgres` leg of the CI matrix.

Without it an understated Postgres floor passes every other check: the SQLite
guard is blind to the Postgres number, and the fully-migrated fixture in
`test_db_adapter.py` satisfies any floor at or below what DBOS currently
reaches. A user sitting at the understated revision would then be told they're
compatible and crash on the missing column — precisely the failure `compat.py`
exists to prevent, on the dialect most deployments run.

The probe migrates a throwaway schema with DBOS' own migration SQL, so it tracks
upstream automatically: no column lists or ordinals are duplicated here.
"""

from __future__ import annotations

import warnings

import pytest
from dbos_argus.compat import required_revision
from dbos_argus.db.base import ArgusDB
from dbos_argus.schema_diff import diff_schemas
from dbos_argus.schema_dump import argus_only, dump_live_schema, load_full_dump
from sqlalchemy import create_engine, text

from .conftest import _to_sync_url

# Kept out of the way of the fixture's own `dbos` schema so the two can coexist
# inside one test session.
PROBE_SCHEMA = "dbos_compat_probe"


class UnverifiedCompatFloorWarning(UserWarning):
    """Raised when the Postgres floor check is skipped for lack of a server.

    A bare `pytest.skip` renders as an unexplained `s` under `-q`, which reads
    like "nothing to see here" — the one impression this skip must not leave,
    since the unchecked field is the one most deployments depend on.
    """


def _migrate_probe_schema(sync_url: str, upto: int) -> None:
    """(Re)create `PROBE_SCHEMA` and apply DBOS' first `upto` Postgres migrations.

    Mirrors `dbos._migration.run_dbos_migrations`' two special cases: online
    migrations need autocommit (they contain CONCURRENTLY index DDL), and
    migration 10 back-fills a primary key that current DBOS already creates in
    migration 1.
    """
    from dbos._migration import _ONLINE_MIGRATIONS, get_dbos_migrations

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PROBE_SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{PROBE_SCHEMA}"'))

        migrations = get_dbos_migrations(PROBE_SCHEMA, use_listen_notify=False)
        for i, sql in enumerate(migrations[:upto], 1):
            if i in _ONLINE_MIGRATIONS:
                with engine.connect() as raw_conn:
                    conn = raw_conn.execution_options(isolation_level="AUTOCOMMIT")
                    conn.execute(text(sql))
                continue
            if i == 10:
                with engine.begin() as conn:
                    already_has_pk = conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.table_constraints "
                            "WHERE table_schema = :schema AND table_name = 'notifications' "
                            "AND constraint_type = 'PRIMARY KEY'"
                        ),
                        {"schema": PROBE_SCHEMA},
                    ).scalar()
                    if not already_has_pk:
                        conn.execute(text(sql))
                continue
            with engine.begin() as conn:
                conn.execute(text(sql))
    finally:
        engine.dispose()


def _drop_probe_schema(sync_url: str) -> None:
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PROBE_SCHEMA}" CASCADE'))
    finally:
        engine.dispose()


async def _argus_columns_missing_at(db: ArgusDB, sync_url: str, revision: int) -> list[str]:
    """Argus-tracked columns absent from a schema migrated to `revision`.

    Runs the production comparator (`diff_schemas`) against the packaged
    snapshot, so this asserts on exactly what `/api/sql-diagnostics` would say.
    """
    _migrate_probe_schema(sync_url, revision)
    async with db.engine.connect() as conn:
        reflected = await dump_live_schema(conn, schema=PROBE_SCHEMA)
    issues = diff_schemas(argus_only(load_full_dump()), reflected)
    return [f"{i.table_name}.{i.column_name or '*'}" for i in issues]


async def test_declared_postgres_floor_is_exact(
    populated_db: tuple[ArgusDB, dict[str, object]],
    db_url: str,
) -> None:
    """The declared Postgres floor must be the *lowest* revision providing every
    argus-tracked column: sufficient at the floor, insufficient one below.

    Flipping a column to `argus: true` without appending a `CompatStep` fails the
    first assert; overstating the floor fails the second. See CONTRIBUTING.md →
    "Bumping the compatibility floor".
    """
    db, _ = populated_db
    if db.dialect != "postgres":
        warnings.warn(
            "Postgres compatibility floor NOT verified in this run "
            f"(compat.py declares {required_revision('postgres')}). This check needs a live "
            "server; the SQLite floor was verified in tests/test_compat.py. An understated "
            "Postgres floor passes every other test and would tell users their database is "
            "compatible when it is not. CI always runs this on the postgres matrix leg. To "
            "run it locally:\n"
            "  docker compose up -d postgres\n"
            "  ARGUS_TEST_DATABASE_URL='postgresql+asyncpg://argus:argus@localhost:5432/argus'"
            " uv run pytest packages/server",
            UnverifiedCompatFloorWarning,
            # stacklevel=1 keeps the attribution on this file. Anything higher
            # walks into asyncio's event-loop internals, since the caller of an
            # async test is the loop, not the test module.
            stacklevel=1,
        )
        pytest.skip("Postgres-only: needs ARGUS_TEST_DATABASE_URL (see warnings summary)")

    sync_url = _to_sync_url(db_url)
    floor = required_revision("postgres")
    try:
        missing_at_floor = await _argus_columns_missing_at(db, sync_url, floor)
        assert missing_at_floor == [], (
            f"Postgres revision {floor} does not provide argus-tracked columns "
            f"{missing_at_floor} — append a CompatStep in compat.py"
        )

        missing_below = await _argus_columns_missing_at(db, sync_url, floor - 1)
        assert missing_below, (
            f"Postgres revision {floor - 1} already provides every argus-tracked "
            f"column, so the declared floor {floor} is higher than necessary"
        )
    finally:
        _drop_probe_schema(sync_url)
