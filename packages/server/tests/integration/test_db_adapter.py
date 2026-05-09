"""Adapter-level integration tests run against either backend.

CI parametrizes the backend by setting `ARGUS_TEST_DATABASE_URL` per
matrix dimension; locally the conftest falls back to a sqlite tempfile.
Each test only knows about the abstract `ArgusDB` interface and the seed
fixture — there is no per-dialect branching here.
"""

from __future__ import annotations

from dbos_argus.db.base import ArgusDB
from dbos_argus.db.rows import NotificationFilters, WorkflowFilters
from dbos_argus.sql_diagnostics import inspect_dbos_schema

# Type alias for the (adapter, seed) tuple yielded by `populated_db`.
DB = tuple[ArgusDB, dict[str, object]]


async def test_healthcheck_succeeds(populated_db: DB) -> None:
    db, _ = populated_db
    # Raises on connection failure; absence of exception is the assert.
    await db.healthcheck()


async def test_reflect_schema_returns_dbos_tables(populated_db: DB) -> None:
    db, _ = populated_db
    dump = await db.reflect_schema(schema="dbos")
    names = {t.name for t in dump.tables}
    # The argus-tracked tables must all be present after migration.
    assert {
        "workflow_status",
        "operation_outputs",
        "notifications",
        "workflow_events",
        "workflow_events_history",
        "workflow_schedules",
        "queues",
    } <= names


async def test_live_schema_matches_pinned_snapshot(populated_db: DB) -> None:
    """`/api/sql-diagnostics` must report `ok: true` after a fresh DBOS
    migration on either backend. Effectively asserts that
    `data/dbos_schema.json` (the single PG-vocabulary snapshot, regenerated
    daily by the watchdog) covers both the Postgres and SQLite migration
    outputs. If DBOS ever ships an argus-tracked column to one dialect but
    not the other, the matrix leg pointing at the affected backend will
    fail here — surfacing drift the PG-only watchdog can't see."""
    db, _ = populated_db
    issues = await inspect_dbos_schema(db)
    assert issues == [], "schema drift: " + "; ".join(i.detail for i in issues)


async def test_list_workflows_grouped_returns_full_tree(populated_db: DB) -> None:
    db, seed = populated_db
    rows = await db.list_workflows(WorkflowFilters(grouped=True))
    # Original family (root + 2 children + grandchild = 4) plus the lone
    # PENDING queue-bound root `wf-q-hb-pend` (5th root with no children).
    # The 3 ENQUEUED queue-bound rows are dropped by the default
    # `status <> 'ENQUEUED'` filter.
    assert len(rows) == 5
    # The original root sits at depth 0 wherever it appears in the DFS;
    # ordering between roots follows updated_at DESC, which the queue-bound
    # root's later seed timestamp now wins.
    by_uuid = {r.workflow_uuid: r for r in rows}
    assert by_uuid[seed["root_id"]].depth == 0
    # The grandchild's depth should be 2 (root → child_success → grandchild).
    grandchild = next(r for r in rows if r.workflow_uuid == seed["grandchild_error_id"])
    assert grandchild.depth == 2


async def test_list_workflows_flat_orders_by_started(populated_db: DB) -> None:
    db, _ = populated_db
    rows = await db.list_workflows(WorkflowFilters(grouped=False))
    # Same 5 as the grouped variant — the default filter strips ENQUEUED.
    assert len(rows) == 5
    # Flat mode: most recent started first.
    started = [r.started_ms for r in rows]
    assert started == sorted(started, reverse=True)


async def test_list_workflows_status_filter(populated_db: DB) -> None:
    db, seed = populated_db
    rows = await db.list_workflows(WorkflowFilters(grouped=False, statuses=["SUCCESS"]))
    assert [r.workflow_uuid for r in rows] == [seed["child_success_id"]]


async def test_list_workflows_q_matches_grandchild(populated_db: DB) -> None:
    db, seed = populated_db
    # Flat mode q matches name OR uuid — `grandchild` only appears in the name.
    rows = await db.list_workflows(WorkflowFilters(grouped=False, q="grandchild"))
    assert [r.workflow_uuid for r in rows] == [seed["grandchild_error_id"]]


async def test_list_workflows_grouped_q_includes_root(populated_db: DB) -> None:
    db, seed = populated_db
    # In grouped mode `q` matches at any depth — the grandchild's match must
    # pull its whole root family into the result, not just the matching row.
    rows = await db.list_workflows(WorkflowFilters(grouped=True, q="grandchild"))
    uuids = {r.workflow_uuid for r in rows}
    assert seed["root_id"] in uuids
    assert seed["grandchild_error_id"] in uuids


async def test_get_workflow_detail_returns_family_steps_events(populated_db: DB) -> None:
    db, seed = populated_db
    detail = await db.get_workflow_detail(seed["child_success_id"])
    # The detail endpoint always expands to the topmost ancestor's whole tree.
    assert {f.workflow_uuid for f in detail.family} == {
        seed["root_id"],
        seed["child_success_id"],
        seed["child_pending_id"],
        seed["grandchild_error_id"],
    }
    # Steps include the seeded operation_outputs rows.
    setevent = next(s for s in detail.steps if s.function_name == "DBOS.setEvent")
    assert setevent.event_key == "demo"  # joined from workflow_events_history
    sleep = next(s for s in detail.steps if s.function_name == "DBOS.sleep")
    assert sleep.sleep_output_raw is not None
    # workflow_events row plus its history row.
    assert any(e.key == "demo" for e in detail.events)


async def test_get_workflow_detail_unknown_returns_empty(populated_db: DB) -> None:
    db, _ = populated_db
    detail = await db.get_workflow_detail("does-not-exist")
    assert detail.family == []
    assert detail.steps == []
    assert detail.events == []


async def test_get_workflow_result_returns_payload(populated_db: DB) -> None:
    db, seed = populated_db
    row = await db.get_workflow_result(seed["child_success_id"])
    assert row is not None
    assert row.output == '"hello"'
    assert row.error is None


async def test_get_workflow_result_missing(populated_db: DB) -> None:
    db, _ = populated_db
    assert await db.get_workflow_result("nope") is None


async def test_get_step_result_returns_payload(populated_db: DB) -> None:
    db, seed = populated_db
    row = await db.get_step_result(seed["child_success_id"], 1)
    assert row is not None
    assert row.output == '"audited"'


async def test_get_step_result_missing(populated_db: DB) -> None:
    db, _ = populated_db
    assert await db.get_step_result("wf-root", 9999) is None


async def test_get_stats_counts_seed(populated_db: DB) -> None:
    db, seed = populated_db
    base_ms: int = int(seed["base_ms"])
    stats = await db.get_stats(since_ms=base_ms - 86_400_000)
    assert stats.total == 8
    # 3 PENDING (root, child_b, hb-pend) + 3 ENQUEUED (hb-enq, plain-enq,
    # orphan-enq); ENQUEUED is part of ACTIVE_STATUSES so it counts as
    # in-flight too.
    assert stats.in_flight == 6
    assert stats.enqueued == 3
    assert stats.failed_recent == 1  # the grandchild ERROR within the window
    assert stats.pending_notifications == 1
    assert stats.active_schedules == 1


async def test_get_throughput_buckets_seed_day(populated_db: DB) -> None:
    db, seed = populated_db
    base_ms: int = int(seed["base_ms"])
    rows = await db.get_throughput(
        since_ms=base_ms - 86_400_000,
        until_ms=base_ms + 86_400_000,
        bucket="day",
    )
    # Bucket boundaries differ by dialect calendar mechanics, but the total
    # of (succeeded + errored + running) across the window must equal the
    # number of seeded workflows. ENQUEUED is part of ACTIVE_STATUSES so the
    # queued seed rows fall into the "running" bucket.
    total = sum(r.succeeded + r.errored + r.running for r in rows)
    assert total == 8


async def test_list_schedules_returns_seeded_schedule(populated_db: DB) -> None:
    db, _ = populated_db
    schedules = await db.list_schedules()
    assert [s.schedule_id for s in schedules] == ["sched-1"]
    assert schedules[0].status == "ACTIVE"


async def test_list_queues_returns_seeded_queues(populated_db: DB) -> None:
    db, _ = populated_db
    queues = await db.list_queues()
    # Alphabetical by name. The seed has an ENQUEUED row on `orphaned-queue`
    # that has no row in `queues`; it must NOT show up here, proving the
    # LEFT JOIN drops orphaned queue_names.
    assert [q.name for q in queues] == ["argus-heartbeats", "plain-queue"]

    rate_limited = queues[0]
    assert rate_limited.rate_limit_max == 10
    assert rate_limited.rate_limit_period_sec == 60.0
    assert rate_limited.concurrency == 5
    assert rate_limited.worker_concurrency == 2
    assert rate_limited.priority_enabled is True
    assert rate_limited.partition_queue is False
    # 1 ENQUEUED + 1 PENDING workflow seeded against this queue.
    assert rate_limited.enqueued == 1
    assert rate_limited.running == 1

    bare = queues[1]
    assert bare.rate_limit_max is None
    assert bare.rate_limit_period_sec is None
    assert bare.concurrency is None
    assert bare.worker_concurrency is None
    assert bare.priority_enabled is False
    # 1 ENQUEUED, no PENDING.
    assert bare.enqueued == 1
    assert bare.running == 0


async def test_list_notifications_includes_ancestor_chain(populated_db: DB) -> None:
    db, seed = populated_db
    result = await db.list_notifications(NotificationFilters())
    assert [n.message_uuid for n in result.notifications] == ["msg-1"]
    assert result.notifications[0].topic == "topic-a"
    # Ancestor walk: child_pending → root, both rows reported.
    seed_id = seed["child_pending_id"]
    chain = [a for a in result.ancestors if a.seed_id == seed_id]
    chain_uuids = {a.workflow_uuid for a in chain}
    assert chain_uuids == {seed["root_id"], seed["child_pending_id"]}


async def test_list_notifications_consumed_filter(populated_db: DB) -> None:
    db, _ = populated_db
    consumed = await db.list_notifications(NotificationFilters(consumed=True))
    assert consumed.notifications == []
    pending = await db.list_notifications(NotificationFilters(consumed=False))
    assert len(pending.notifications) == 1
