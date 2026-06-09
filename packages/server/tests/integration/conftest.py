"""Integration-test fixtures for the `ArgusDB` adapters.

CI runs this suite once per backend by setting `ARGUS_TEST_DATABASE_URL`
to a Postgres or SQLite URL; locally the suite falls back to a sqlite
tempfile so it works offline.

The fixture bootstraps the DBOS system schema using DBOS's own migration
SQL (`dbos._migration`) — same authority that creates the schema in a
real DBOS app — then inserts a small but representative seed:

    wf-root (PENDING)
    ├── wf-child-success (SUCCESS)              ← has output, one event, three steps
    │   └── wf-grandchild-error (ERROR)         ← has error
    └── wf-child-pending (PENDING)              ← has one pending notification

…plus one workflow_schedule. That's enough to exercise every endpoint
shape (DFS family, status filters, search, op counts, events,
notifications + ancestor chain, schedules, stats, throughput) without
each test having to assemble its own data.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dbos_argus.db.base import ArgusDB
from dbos_argus.db.postgres import PostgresArgusDB
from dbos_argus.db.sqlite import SqliteArgusDB
from dbos_argus.settings import Settings
from sqlalchemy import create_engine, text

# Tables the DBOS schema owns. Listed explicitly (rather than introspected)
# so a missing-table bug in the adapter can't hide a half-cleaned fixture.
_DBOS_TABLES = (
    "workflow_events_history",
    "workflow_events",
    "workflow_schedules",
    "queues",
    "notifications",
    "streams",
    "operation_outputs",
    "workflow_status",
    "application_versions",
    "dbos_migrations",
)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _to_sync_url(async_url: str) -> str:
    """Async drivers can't run multi-statement migrations cleanly. Map each
    async URL to a sync sibling whose driver we already have installed
    (psycopg / pysqlite)."""
    if async_url.startswith("sqlite+aiosqlite://"):
        return "sqlite://" + async_url[len("sqlite+aiosqlite://") :]
    if async_url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + async_url[len("postgresql+asyncpg://") :]
    return async_url


def _bootstrap_postgres(sync_url: str) -> None:
    # Use DBOS' own helpers — they handle the migration-10 PK-already-exists
    # corner case that the raw migration list does not.
    from dbos._migration import ensure_dbos_schema, run_dbos_migrations

    eng = create_engine(sync_url)
    try:
        ensure_dbos_schema(eng, "dbos")
        run_dbos_migrations(eng, "dbos", use_listen_notify=False)
    finally:
        eng.dispose()


def _bootstrap_sqlite(sync_url: str) -> None:
    from dbos._migration import sqlite_migrations

    eng = create_engine(sync_url)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS dbos_migrations "
                    "(version INTEGER NOT NULL PRIMARY KEY)"
                )
            )
            applied = conn.execute(text("SELECT version FROM dbos_migrations")).fetchone()
            last = applied[0] if applied else 0
            for i, mig in enumerate(sqlite_migrations, 1):
                if i <= last:
                    continue
                # SQLite drivers run one statement per execute() call.
                for stmt in (s.strip() for s in mig.split(";") if s.strip()):
                    conn.execute(text(stmt))
                if last == 0:
                    conn.execute(
                        text("INSERT INTO dbos_migrations (version) VALUES (:v)"),
                        {"v": i},
                    )
                else:
                    conn.execute(text("UPDATE dbos_migrations SET version = :v"), {"v": i})
                last = i
    finally:
        eng.dispose()


def _drop(sync_url: str) -> None:
    """Reset state between tests — Postgres uses CASCADE on the schema; SQLite
    drops each table individually since it has no schema namespace."""
    eng = create_engine(sync_url)
    try:
        with eng.begin() as conn:
            if _is_sqlite(sync_url):
                for t in _DBOS_TABLES:
                    conn.execute(text(f'DROP TABLE IF EXISTS "{t}"'))
            else:
                conn.execute(text('DROP SCHEMA IF EXISTS "dbos" CASCADE'))
    finally:
        eng.dispose()


def _seed(sync_url: str, base_ms: int) -> dict[str, object]:
    """Insert the canonical fixture tree. Same INSERTs work on both backends —
    `dbos.` prefix is the only difference, and that's parametrized."""
    p = "" if _is_sqlite(sync_url) else "dbos."
    eng = create_engine(sync_url)
    try:
        with eng.begin() as conn:
            # workflow_status family. created_at is millisecond-offset from
            # base_ms so tests can assert ordering deterministically.
            #
            # The four `wf-q-*` rows exist so list_queues' per-queue
            # ENQUEUED/running aggregate has something to match against:
            #   - argus-heartbeats: 1 ENQUEUED + 1 PENDING
            #   - plain-queue:      1 ENQUEUED
            #   - orphaned-queue:   1 ENQUEUED, no row in `queues` — gets
            #     dropped by the LEFT JOIN, so the registered-queue list
            #     never inflates with orphan counts.
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}workflow_status
                        (workflow_uuid, status, name, executor_id, created_at, updated_at,
                         recovery_attempts, started_at_epoch_ms, priority,
                         parent_workflow_id, output, error, serialization, queue_name,
                         completed_at)
                    VALUES
                        ('wf-root', 'PENDING', 'root_workflow', 'test',
                         :t0, :t0, 0, :t0, 0, NULL, NULL, NULL, 'portable_json', NULL, NULL),
                        ('wf-child-success', 'SUCCESS', 'child_a', 'test',
                         :t1, :t1, 0, :t1, 0, 'wf-root', '"hello"', NULL,
                         'portable_json', NULL, :c1),
                        ('wf-child-pending', 'PENDING', 'child_b', 'test',
                         :t2, :t2, 0, :t2, 0, 'wf-root', NULL, NULL, 'portable_json', NULL, NULL),
                        ('wf-grandchild-error', 'ERROR', 'grandchild', 'test',
                         :t3, :t3, 0, :t3, 0, 'wf-child-success', NULL, '"boom"',
                         'portable_json', NULL, :c3),
                        ('wf-q-hb-enq', 'ENQUEUED', 'queued_a', 'test',
                         :t4, :t4, 0, NULL, 0, NULL, NULL, NULL,
                         'portable_json', 'argus-heartbeats', NULL),
                        ('wf-q-hb-pend', 'PENDING', 'queued_b', 'test',
                         :t5, :t5, 0, :t5, 0, NULL, NULL, NULL,
                         'portable_json', 'argus-heartbeats', NULL),
                        ('wf-q-plain-enq', 'ENQUEUED', 'queued_c', 'test',
                         :t6, :t6, 0, NULL, 0, NULL, NULL, NULL,
                         'portable_json', 'plain-queue', NULL),
                        ('wf-q-orphan-enq', 'ENQUEUED', 'queued_d', 'test',
                         :t7, :t7, 0, NULL, 0, NULL, NULL, NULL,
                         'portable_json', 'orphaned-queue', NULL)
                    """
                ),
                {
                    "t0": base_ms,
                    "t1": base_ms + 100,
                    "t2": base_ms + 200,
                    "t3": base_ms + 300,
                    "t4": base_ms + 400,
                    "t5": base_ms + 500,
                    "t6": base_ms + 600,
                    "t7": base_ms + 700,
                    # Terminal workflows carry completed_at; PENDING/ENQUEUED
                    # rows leave it NULL. wf-child-success finishes 150ms after
                    # it started (t1), the errored grandchild 50ms after t3.
                    "c1": base_ms + 250,
                    "c3": base_ms + 350,
                },
            )
            # operation_outputs: an audit, a setEvent (joined to events_history
            # below), a sleep (so sleep_requested_ms gets exercised), and an
            # error step on the grandchild.
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}operation_outputs
                        (workflow_uuid, function_id, function_name, output, error,
                         child_workflow_id, started_at_epoch_ms, completed_at_epoch_ms,
                         serialization)
                    VALUES
                        ('wf-child-success', 1, 'audit', '"audited"', NULL, NULL,
                         :t1, :t2, 'portable_json'),
                        ('wf-child-success', 2, 'DBOS.setEvent', NULL, NULL, NULL,
                         :t2, :t3, 'portable_json'),
                        ('wf-child-success', 3, 'DBOS.sleep', :sleep_out, NULL, NULL,
                         :t3, :t3, 'portable_json'),
                        ('wf-grandchild-error', 1, 'failing_step', NULL, '"boom"', NULL,
                         :t1, :t2, 'portable_json')
                    """
                ),
                {
                    "t1": base_ms + 100,
                    "t2": base_ms + 200,
                    "t3": base_ms + 300,
                    # DBOS.sleep stores wakeup time as a unix-seconds string;
                    # `_sleep_requested_ms` derives 500ms from this row.
                    "sleep_out": str((base_ms + 800) / 1000),
                },
            )
            # workflow_events + history (must match function_id=2 above so
            # the JOIN in get_steps populates `event_key`).
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}workflow_events (workflow_uuid, key, value, serialization)
                    VALUES ('wf-child-success', 'demo', '"hi"', 'portable_json')
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}workflow_events_history
                        (workflow_uuid, function_id, key, value, serialization)
                    VALUES ('wf-child-success', 2, 'demo', '"hi"', 'portable_json')
                    """
                )
            )
            # notification: targets wf-child-pending so the ancestor chain
            # walk has something to walk (child → root).
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}notifications
                        (message_uuid, destination_uuid, topic, message,
                         created_at_epoch_ms, serialization, consumed)
                    VALUES ('msg-1', 'wf-child-pending', 'topic-a', '"payload"',
                            :t, 'portable_json', :consumed)
                    """
                ),
                {"t": base_ms + 50, "consumed": False},
            )
            # one ACTIVE schedule
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}workflow_schedules
                        (schedule_id, schedule_name, workflow_name, workflow_class_name,
                         schedule, status, context, automatic_backfill)
                    VALUES ('sched-1', 'demo-schedule', 'demo_wf', NULL,
                            '*/5 * * * *', 'ACTIVE', '{{}}', :b)
                    """
                ),
                {"b": False},
            )
            # two registered queues — one with a rate limiter, one bare — so
            # list_queues exercises both null-config and populated-config paths.
            conn.execute(
                text(
                    f"""
                    INSERT INTO {p}queues
                        (queue_id, name, concurrency, worker_concurrency,
                         rate_limit_max, rate_limit_period_sec,
                         priority_enabled, partition_queue, polling_interval_sec,
                         created_at, updated_at)
                    VALUES
                        ('q-1', 'argus-heartbeats', 5, 2,
                         10, 60.0, :pri, :part, 1.0, :t, :t),
                        ('q-2', 'plain-queue', NULL, NULL,
                         NULL, NULL, :pri_off, :part, 1.0, :t, :t)
                    """
                ),
                {
                    "pri": True,
                    "pri_off": False,
                    "part": False,
                    "t": base_ms,
                },
            )
    finally:
        eng.dispose()
    return {
        "root_id": "wf-root",
        "child_success_id": "wf-child-success",
        "child_pending_id": "wf-child-pending",
        "grandchild_error_id": "wf-grandchild-error",
        "base_ms": base_ms,
    }


@pytest.fixture(scope="session")
def db_url() -> AsyncIterator[str]:
    """The async URL the adapter under test connects with."""
    explicit = os.environ.get("ARGUS_TEST_DATABASE_URL")
    if explicit:
        # Normalize to the async driver Argus expects, so CI users can paste
        # a plain libpq URL.
        if explicit.startswith("postgresql://") or explicit.startswith("postgres://"):
            scheme, rest = explicit.split("://", 1)
            yield f"postgresql+asyncpg://{rest}"
        elif explicit.startswith("sqlite://") and not explicit.startswith("sqlite+"):
            yield "sqlite+aiosqlite://" + explicit[len("sqlite://") :]
        else:
            yield explicit
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix="argus-it-"))
    try:
        yield f"sqlite+aiosqlite:///{tmp_dir / 'argus.sqlite'}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _make_adapter(url: str) -> ArgusDB:
    settings = Settings(database_url=url)
    return SqliteArgusDB(settings) if _is_sqlite(url) else PostgresArgusDB(settings)


@pytest.fixture
async def populated_db(db_url: str) -> AsyncIterator[tuple[ArgusDB, dict[str, object]]]:
    """Reset the DBOS schema, run migrations, seed fixture rows, yield a
    fresh adapter. Disposes the engine on teardown so each test starts
    with no shared connection state."""
    sync_url = _to_sync_url(db_url)
    _drop(sync_url)
    if _is_sqlite(db_url):
        _bootstrap_sqlite(sync_url)
    else:
        _bootstrap_postgres(sync_url)
    seed = _seed(sync_url, base_ms=1_700_000_000_000)

    adapter = _make_adapter(db_url)
    try:
        yield adapter, seed
    finally:
        await adapter.engine.dispose()
