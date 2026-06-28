"""Postgres `ArgusDB` adapter.

Owns the asyncpg engine and every Postgres-flavored SQL string the endpoints
need. The SQL is transcribed verbatim from the pre-adapter `main.py`; the only
difference is that results are mapped into `rows.py` dataclasses rather than
fed directly into Pydantic models.

Missing-schema handling: if the `dbos.*` tables don't exist yet (no DBOS app
has connected), reads return empty/sentinel values instead of raising. That
matches the original behavior — the console renders an empty state.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from ..schema_dump import SchemaDump, dump_live_schema
from ..settings import Settings
from ..workflow_status import ACTIVE_STATUSES_SQL, ERROR_STATUSES_SQL
from .base import ArgusDB
from .rows import (
    AncestorRow,
    EventRow,
    NotificationFilters,
    NotificationRow,
    NotificationsRows,
    QueueRow,
    ResultRow,
    ScheduleRow,
    StatsRow,
    StepRow,
    ThroughputRow,
    WorkflowDetailRows,
    WorkflowFamilyRow,
    WorkflowFilters,
    WorkflowListRow,
    normalize_json_value,
)

# Bucket → date_trunc unit (interpolated into SQL — closed set).
_BUCKET_UNIT: dict[str, str] = {"hour": "hour", "day": "day"}


def _build_workflow_sql(grouped: bool, filters: WorkflowFilters) -> tuple[str, dict[str, object]]:
    """Render the list-workflows SQL + bound params for the given filters.

    In grouped mode, filters apply to the `roots` CTE only — matching roots
    come along with their entire descendant tree. Each row's sort_path is the
    accumulated started_ms from root down to itself — Postgres array ordering
    then yields a DFS traversal with children sitting directly under their
    parent.

    In flat mode, filters apply to all workflows; no recursion, ordered by
    started_at DESC.
    """
    params: dict[str, object] = {"limit": filters.limit}
    # Conditions that scope what counts as a "root" in grouped mode (and match
    # rows directly in flat mode). `q` is handled separately because in grouped
    # mode we want it to match anywhere in the tree, not just at the root.
    root_conditions: list[str] = []

    if filters.started_after_ms is not None:
        root_conditions.append("COALESCE(started_at_epoch_ms, created_at) >= :started_after_ms")
        params["started_after_ms"] = filters.started_after_ms
    if filters.started_before_ms is not None:
        root_conditions.append("COALESCE(started_at_epoch_ms, created_at) <= :started_before_ms")
        params["started_before_ms"] = filters.started_before_ms
    if filters.statuses:
        root_conditions.append("status = ANY(:statuses)")
        params["statuses"] = filters.statuses
    else:
        # ENQUEUED runs are surfaced in the workflow-list page's pinned strip,
        # so the main list defaults to hiding them. An explicit `status` filter
        # opts back in (the strip uses ?status=ENQUEUED).
        root_conditions.append("status <> 'ENQUEUED'")
    if filters.queue_name:
        root_conditions.append("queue_name = :queue_name")
        params["queue_name"] = filters.queue_name
    # Scheduled workflow runs use the deterministic id `sched-<schedule_name>-<isoformat>`
    # (or `sched-<func_name>-<isoformat>` from the deprecated decorator path). DBOS does
    # not record an explicit "is scheduled" flag on workflow_status, so filtering by id
    # prefix is the canonical detection — see dbos/_scheduler.py:171.
    if filters.hide_scheduled:
        root_conditions.append("workflow_uuid NOT LIKE 'sched-%'")

    has_q = bool(filters.q)
    if has_q:
        params["q_pat"] = f"%{filters.q}%"

    where_extra = (" AND " + " AND ".join(root_conditions)) if root_conditions else ""

    # Operation counts come from a single GROUP BY scoped to the workflow_uuids
    # we're returning — much cheaper than N+1 correlated subqueries on large
    # operation_outputs tables.
    if grouped:
        # In grouped mode `q` matches at any depth: find any workflow whose
        # uuid/name matches, walk up parent_workflow_id to find its root, then
        # include that root's full subtree below. Without this, searching for
        # a child name (e.g. "dispatch") would miss roots whose own name
        # doesn't contain the term.
        if has_q:
            match_ctes = """
                upward AS (
                    SELECT workflow_uuid, parent_workflow_id
                    FROM dbos.workflow_status
                    WHERE workflow_uuid ILIKE :q_pat OR name ILIKE :q_pat
                    UNION
                    SELECT ws.workflow_uuid, ws.parent_workflow_id
                    FROM dbos.workflow_status ws
                    JOIN upward u ON u.parent_workflow_id = ws.workflow_uuid
                ),
                matched_roots AS (
                    SELECT DISTINCT workflow_uuid
                    FROM upward
                    WHERE parent_workflow_id IS NULL
                ),
            """
            match_filter = " AND workflow_uuid IN (SELECT workflow_uuid FROM matched_roots)"
        else:
            match_ctes = ""
            match_filter = ""
        sql = f"""
            WITH RECURSIVE
                {match_ctes}roots AS (
                    SELECT workflow_uuid, updated_at
                    FROM dbos.workflow_status
                    WHERE parent_workflow_id IS NULL{where_extra}{match_filter}
                    ORDER BY updated_at DESC
                    LIMIT :limit
                ),
                tree AS (
                    SELECT
                        ws.workflow_uuid,
                        ws.parent_workflow_id,
                        ws.name,
                        ws.status,
                        ws.queue_name,
                        ws.executor_id,
                        ws.priority,
                        COALESCE(ws.started_at_epoch_ms, ws.created_at) AS started_ms,
                        ws.updated_at AS updated_ms,
                        ws.completed_at AS completed_ms,
                        0 AS depth,
                        r.updated_at AS root_updated_at,
                        ARRAY[COALESCE(ws.started_at_epoch_ms, ws.created_at)] AS sort_path
                    FROM dbos.workflow_status ws
                    JOIN roots r ON ws.workflow_uuid = r.workflow_uuid

                    UNION ALL

                    SELECT
                        c.workflow_uuid,
                        c.parent_workflow_id,
                        c.name,
                        c.status,
                        c.queue_name,
                        c.executor_id,
                        c.priority,
                        COALESCE(c.started_at_epoch_ms, c.created_at),
                        c.updated_at,
                        c.completed_at,
                        t.depth + 1,
                        t.root_updated_at,
                        t.sort_path || COALESCE(c.started_at_epoch_ms, c.created_at)
                    FROM dbos.workflow_status c
                    JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
                ),
                op_counts AS (
                    SELECT workflow_uuid, COUNT(*)::bigint AS op_count
                    FROM dbos.operation_outputs
                    WHERE workflow_uuid IN (SELECT workflow_uuid FROM tree)
                    GROUP BY workflow_uuid
                )
            SELECT
                t.workflow_uuid, t.parent_workflow_id, t.name, t.status,
                t.queue_name, t.executor_id, t.priority,
                t.started_ms, t.updated_ms, t.completed_ms, t.depth,
                COALESCE(oc.op_count, 0)::bigint AS op_count
            FROM tree t
            LEFT JOIN op_counts oc ON oc.workflow_uuid = t.workflow_uuid
            ORDER BY t.root_updated_at DESC, t.sort_path ASC
        """
    else:
        # Flat mode: each row is independent, so `q` filters rows directly
        # alongside the other conditions.
        flat_conditions = list(root_conditions)
        if has_q:
            flat_conditions.append("(workflow_uuid ILIKE :q_pat OR name ILIKE :q_pat)")
        flat_where_extra = (" AND " + " AND ".join(flat_conditions)) if flat_conditions else ""
        flat_where = f"WHERE 1=1{flat_where_extra}" if flat_where_extra else ""
        sql = f"""
            WITH chosen AS (
                SELECT
                    workflow_uuid, parent_workflow_id, name, status, queue_name, executor_id,
                    priority,
                    COALESCE(started_at_epoch_ms, created_at) AS started_ms,
                    updated_at AS updated_ms,
                    completed_at AS completed_ms
                FROM dbos.workflow_status
                {flat_where}
                ORDER BY COALESCE(started_at_epoch_ms, created_at) DESC
                LIMIT :limit
            ),
            op_counts AS (
                SELECT workflow_uuid, COUNT(*)::bigint AS op_count
                FROM dbos.operation_outputs
                WHERE workflow_uuid IN (SELECT workflow_uuid FROM chosen)
                GROUP BY workflow_uuid
            )
            SELECT
                c.workflow_uuid, c.parent_workflow_id, c.name, c.status,
                c.queue_name, c.executor_id, c.priority,
                c.started_ms, c.updated_ms, c.completed_ms,
                0 AS depth,
                COALESCE(oc.op_count, 0)::bigint AS op_count
            FROM chosen c
            LEFT JOIN op_counts oc ON oc.workflow_uuid = c.workflow_uuid
            ORDER BY c.started_ms DESC
        """
    return sql, params


_FAMILY_SQL = """
    WITH RECURSIVE
        up AS (
            SELECT workflow_uuid, parent_workflow_id, 0 AS lvl
            FROM dbos.workflow_status
            WHERE workflow_uuid = :workflow_id

            UNION ALL

            SELECT ws.workflow_uuid, ws.parent_workflow_id, u.lvl + 1
            FROM dbos.workflow_status ws
            JOIN up u ON ws.workflow_uuid = u.parent_workflow_id
        ),
        root AS (
            SELECT workflow_uuid
            FROM up
            ORDER BY lvl DESC
            LIMIT 1
        ),
        tree AS (
            SELECT
                ws.workflow_uuid,
                ws.parent_workflow_id,
                ws.name,
                ws.status,
                ws.queue_name,
                ws.executor_id,
                ws.schedule_name,
                ws.attributes,
                ws.recovery_attempts,
                ws.workflow_timeout_ms,
                ws.output IS NOT NULL AS has_output,
                ws.error IS NOT NULL AS has_error,
                COALESCE(ws.started_at_epoch_ms, ws.created_at) AS started_ms,
                ws.updated_at AS updated_ms,
                ws.completed_at AS completed_ms,
                0 AS depth,
                ARRAY[COALESCE(ws.started_at_epoch_ms, ws.created_at)] AS sort_path
            FROM dbos.workflow_status ws
            JOIN root r ON ws.workflow_uuid = r.workflow_uuid

            UNION ALL

            SELECT
                c.workflow_uuid,
                c.parent_workflow_id,
                c.name,
                c.status,
                c.queue_name,
                c.executor_id,
                c.schedule_name,
                c.attributes,
                c.recovery_attempts,
                c.workflow_timeout_ms,
                c.output IS NOT NULL,
                c.error IS NOT NULL,
                COALESCE(c.started_at_epoch_ms, c.created_at),
                c.updated_at,
                c.completed_at,
                t.depth + 1,
                t.sort_path || COALESCE(c.started_at_epoch_ms, c.created_at)
            FROM dbos.workflow_status c
            JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
        )
    SELECT
        workflow_uuid, parent_workflow_id, name, status, queue_name, executor_id,
        schedule_name, attributes, recovery_attempts, workflow_timeout_ms,
        has_output, has_error, started_ms, updated_ms, completed_ms, depth
    FROM tree
    ORDER BY sort_path ASC
"""


# Sleep rows store the raw wakeup-time string in `output`. We carry it through
# under a dedicated alias so main.py can compute sleep_requested_ms in Python
# without shipping every step's payload to the client.
_STEPS_SQL = """
    SELECT
        o.workflow_uuid,
        o.function_id,
        o.function_name,
        o.output IS NOT NULL AS has_output,
        o.error IS NOT NULL AS has_error,
        o.child_workflow_id,
        o.started_at_epoch_ms,
        o.completed_at_epoch_ms,
        seh.key AS event_key,
        CASE WHEN o.function_name = 'DBOS.sleep' THEN o.output END AS sleep_output_raw
    FROM dbos.operation_outputs o
    LEFT JOIN dbos.workflow_events_history seh
        ON o.function_name = 'DBOS.setEvent'
        AND seh.workflow_uuid = o.workflow_uuid
        AND seh.function_id = o.function_id
    WHERE o.workflow_uuid = ANY(:workflow_ids)
    ORDER BY o.workflow_uuid, o.function_id ASC
"""


# Joins each `dbos.workflow_events` row (current value per key) to every
# corresponding `dbos.workflow_events_history` row (one per setEvent call) and
# to `dbos.operation_outputs` for the call's completed_at. One row per
# historical set; the current value repeats per row and is collapsed in
# Python below.
_EVENTS_SQL = """
    SELECT
        we.workflow_uuid,
        we.key,
        we.value AS current_value,
        we.serialization AS current_serialization,
        weh.function_id,
        weh.value AS history_value,
        weh.serialization AS history_serialization,
        o.completed_at_epoch_ms
    FROM dbos.workflow_events we
    LEFT JOIN dbos.workflow_events_history weh
        ON weh.workflow_uuid = we.workflow_uuid AND weh.key = we.key
    LEFT JOIN dbos.operation_outputs o
        ON o.workflow_uuid = weh.workflow_uuid
            AND o.function_id = weh.function_id
    WHERE we.workflow_uuid = ANY(:workflow_ids)
    ORDER BY we.workflow_uuid, we.key, weh.function_id ASC
"""


_WORKFLOW_RESULT_SQL = """
    SELECT output, error, serialization
    FROM dbos.workflow_status
    WHERE workflow_uuid = :workflow_id
"""


_STEP_RESULT_SQL = """
    SELECT output, error, serialization
    FROM dbos.operation_outputs
    WHERE workflow_uuid = :workflow_id AND function_id = :function_id
"""


_STATS_SQL = f"""
    SELECT
        (SELECT COUNT(*) FROM dbos.workflow_status) AS total,
        (SELECT COUNT(*) FROM dbos.workflow_status
            WHERE status IN {ACTIVE_STATUSES_SQL}) AS in_flight,
        (SELECT COUNT(*) FROM dbos.workflow_status
            WHERE status = 'ENQUEUED') AS enqueued,
        (SELECT COUNT(*) FROM dbos.workflow_status
            WHERE status IN {ERROR_STATUSES_SQL}
            AND COALESCE(started_at_epoch_ms, created_at) >= :since_ms) AS failed_recent,
        (SELECT COUNT(*) FROM dbos.notifications
            WHERE consumed = false) AS pending_notifications,
        (SELECT COUNT(*) FROM dbos.workflow_schedules
            WHERE status = 'ACTIVE') AS active_schedules,
        (SELECT COUNT(*) FROM dbos.queues) AS total_queues
"""


_SCHEDULES_SQL = """
    SELECT
        schedule_id, schedule_name, workflow_name, workflow_class_name,
        schedule, status, last_fired_at, automatic_backfill,
        cron_timezone, queue_name
    FROM dbos.workflow_schedules
    ORDER BY schedule_name ASC
"""


# Aggregate ENQUEUED + PENDING per queue in a single subquery so we get both
# counts in one pass over the in-flight partial index
# (`idx_workflow_status_in_flight`, partial WHERE status IN ('ENQUEUED','PENDING')),
# then LEFT JOIN onto dbos.queues. Queues with no live workflows fall through
# as zeros via COALESCE.
_QUEUES_SQL = """
    SELECT
        q.queue_id, q.name, q.concurrency, q.worker_concurrency,
        q.rate_limit_max, q.rate_limit_period_sec,
        q.priority_enabled, q.partition_queue, q.polling_interval_sec,
        q.created_at, q.updated_at,
        COALESCE(c.enqueued, 0)::bigint AS enqueued,
        COALESCE(c.running, 0)::bigint AS running
    FROM dbos.queues q
    LEFT JOIN (
        SELECT
            queue_name,
            COUNT(*) FILTER (WHERE status = 'ENQUEUED') AS enqueued,
            COUNT(*) FILTER (WHERE status = 'PENDING') AS running
        FROM dbos.workflow_status
        WHERE queue_name IS NOT NULL
          AND status IN ('ENQUEUED', 'PENDING')
        GROUP BY queue_name
    ) c ON c.queue_name = q.name
    ORDER BY q.name ASC
"""


# Walks parent_workflow_id from each destination up to the topmost ancestor in
# one set-based recursive CTE. Tracks the seed destination so results can be
# grouped per-notification client-side.
_NOTIFICATION_ANCESTORS_SQL = """
    WITH RECURSIVE up AS (
        SELECT
            ws.workflow_uuid AS seed_id,
            ws.workflow_uuid,
            ws.parent_workflow_id,
            ws.name,
            ws.status,
            0 AS lvl
        FROM dbos.workflow_status ws
        WHERE ws.workflow_uuid = ANY(:destination_ids)

        UNION ALL

        SELECT
            u.seed_id,
            ws.workflow_uuid,
            ws.parent_workflow_id,
            ws.name,
            ws.status,
            u.lvl + 1
        FROM dbos.workflow_status ws
        JOIN up u ON ws.workflow_uuid = u.parent_workflow_id
    )
    SELECT seed_id, workflow_uuid, name, status, lvl
    FROM up
    ORDER BY seed_id, lvl DESC
"""


_EMPTY_STATS = StatsRow(
    total=0,
    in_flight=0,
    enqueued=0,
    failed_recent=0,
    pending_notifications=0,
    active_schedules=0,
    total_queues=0,
)


class PostgresArgusDB(ArgusDB):
    """asyncpg-backed adapter for DBOS Postgres system databases."""

    def __init__(self, settings: Settings) -> None:
        url, connect_args = settings.asyncpg_engine_args()
        self.engine = create_async_engine(url, echo=False, future=True, connect_args=connect_args)
        self._server_version: str | None = None

    @property
    def display_url(self) -> str:
        return self.engine.url.render_as_string(hide_password=True)

    @property
    def dialect(self) -> Literal["postgres", "sqlite"]:
        return "postgres"

    async def healthcheck(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def server_version(self) -> str | None:
        if self._server_version is not None:
            return self._server_version
        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(text("SHOW server_version"))
                row = result.fetchone()
        except SQLAlchemyError:
            return None
        if row is None or row[0] is None:
            return None
        # Postgres returns the full string like "16.4 (Debian …)"; trim to the
        # leading version token so the UI footer stays compact.
        version = str(row[0]).split()[0]
        self._server_version = version
        return version

    async def dbos_schema_revision(self) -> int | None:
        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT version FROM dbos.dbos_migrations LIMIT 1")
                )
                row = result.fetchone()
        except SQLAlchemyError:
            # Table doesn't exist yet (no DBOS app migrated this DB) or the
            # probe failed for transient reasons.
            return None
        if row is None or row[0] is None:
            return None
        return int(row[0])

    async def reflect_schema(self, schema: str = "dbos") -> SchemaDump:
        async with self.engine.connect() as conn:
            return await dump_live_schema(conn, schema=schema)

    async def list_workflows(self, filters: WorkflowFilters) -> list[WorkflowListRow]:
        sql, params = _build_workflow_sql(filters.grouped, filters)
        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                rows = result.fetchall()
        except ProgrammingError:
            return []
        return [
            WorkflowListRow(
                workflow_uuid=r.workflow_uuid,
                parent_workflow_id=r.parent_workflow_id,
                name=r.name,
                status=r.status,
                queue_name=r.queue_name,
                executor_id=r.executor_id,
                priority=r.priority,
                started_ms=r.started_ms,
                updated_ms=r.updated_ms,
                completed_ms=r.completed_ms,
                depth=r.depth,
                op_count=r.op_count,
            )
            for r in rows
        ]

    async def get_workflow_detail(self, workflow_id: str) -> WorkflowDetailRows:
        try:
            async with self.engine.connect() as conn:
                family_rows = (
                    await conn.execute(text(_FAMILY_SQL), {"workflow_id": workflow_id})
                ).fetchall()
                family_ids = [r.workflow_uuid for r in family_rows]
                step_rows = (
                    await conn.execute(text(_STEPS_SQL), {"workflow_ids": family_ids})
                ).fetchall()
                event_rows = (
                    await conn.execute(text(_EVENTS_SQL), {"workflow_ids": family_ids})
                ).fetchall()
        except ProgrammingError:
            return WorkflowDetailRows(family=[], steps=[], events=[])

        family = [
            WorkflowFamilyRow(
                workflow_uuid=r.workflow_uuid,
                parent_workflow_id=r.parent_workflow_id,
                name=r.name,
                status=r.status,
                queue_name=r.queue_name,
                executor_id=r.executor_id,
                schedule_name=r.schedule_name,
                attributes=normalize_json_value(r.attributes),
                recovery_attempts=r.recovery_attempts,
                workflow_timeout_ms=r.workflow_timeout_ms,
                has_output=r.has_output,
                has_error=r.has_error,
                started_ms=r.started_ms,
                updated_ms=r.updated_ms,
                completed_ms=r.completed_ms,
                depth=r.depth,
            )
            for r in family_rows
        ]
        steps = [
            StepRow(
                workflow_uuid=s.workflow_uuid,
                function_id=s.function_id,
                function_name=s.function_name,
                has_output=s.has_output,
                has_error=s.has_error,
                child_workflow_id=s.child_workflow_id,
                started_at_epoch_ms=s.started_at_epoch_ms,
                completed_at_epoch_ms=s.completed_at_epoch_ms,
                event_key=s.event_key,
                sleep_output_raw=s.sleep_output_raw,
            )
            for s in step_rows
        ]
        events = [
            EventRow(
                workflow_uuid=e.workflow_uuid,
                key=e.key,
                current_value=e.current_value,
                current_serialization=e.current_serialization,
                function_id=e.function_id,
                history_value=e.history_value,
                history_serialization=e.history_serialization,
                completed_at_epoch_ms=e.completed_at_epoch_ms,
            )
            for e in event_rows
        ]
        return WorkflowDetailRows(family=family, steps=steps, events=events)

    async def get_workflow_result(self, workflow_id: str) -> ResultRow | None:
        try:
            async with self.engine.connect() as conn:
                row = (
                    await conn.execute(text(_WORKFLOW_RESULT_SQL), {"workflow_id": workflow_id})
                ).fetchone()
        except ProgrammingError:
            return None
        if row is None:
            return None
        return ResultRow(output=row.output, error=row.error, serialization=row.serialization)

    async def get_step_result(self, workflow_id: str, function_id: int) -> ResultRow | None:
        try:
            async with self.engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(_STEP_RESULT_SQL),
                        {"workflow_id": workflow_id, "function_id": function_id},
                    )
                ).fetchone()
        except ProgrammingError:
            return None
        if row is None:
            return None
        return ResultRow(output=row.output, error=row.error, serialization=row.serialization)

    async def get_stats(self, since_ms: int) -> StatsRow:
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(_STATS_SQL), {"since_ms": since_ms})).fetchone()
        except ProgrammingError:
            return _EMPTY_STATS
        if row is None:
            return _EMPTY_STATS
        return StatsRow(
            total=row.total,
            in_flight=row.in_flight,
            enqueued=row.enqueued,
            failed_recent=row.failed_recent,
            pending_notifications=row.pending_notifications,
            active_schedules=row.active_schedules,
            total_queues=row.total_queues,
        )

    async def get_throughput(
        self, since_ms: int, until_ms: int, bucket: Literal["hour", "day"]
    ) -> list[ThroughputRow]:
        unit = _BUCKET_UNIT[bucket]
        # Bucket unit comes from a closed literal mapping above — safe to interpolate.
        sql = f"""
            WITH params AS (
                SELECT
                    CAST(:since_ms AS bigint) AS since_ms,
                    CAST(:until_ms AS bigint) AS until_ms
            ),
            buckets AS (
                SELECT generate_series(
                    date_trunc('{unit}', to_timestamp(p.since_ms / 1000.0)),
                    date_trunc('{unit}', to_timestamp(p.until_ms / 1000.0)),
                    '1 {unit}'::interval
                ) AS ts
                FROM params p
            ),
            events AS (
                SELECT
                    date_trunc('{unit}', to_timestamp(ws.created_at / 1000.0)) AS ts,
                    ws.status
                FROM dbos.workflow_status ws, params p
                WHERE ws.created_at >= p.since_ms AND ws.created_at <= p.until_ms
            )
            SELECT
                b.ts AS ts,
                COUNT(e.*) FILTER (WHERE e.status = 'SUCCESS') AS succeeded,
                COUNT(e.*) FILTER (WHERE e.status IN {ERROR_STATUSES_SQL}) AS errored,
                COUNT(e.*) FILTER (WHERE e.status IN {ACTIVE_STATUSES_SQL}) AS running
            FROM buckets b
            LEFT JOIN events e ON e.ts = b.ts
            GROUP BY b.ts
            ORDER BY b.ts ASC
        """
        try:
            async with self.engine.connect() as conn:
                rows = (
                    await conn.execute(text(sql), {"since_ms": since_ms, "until_ms": until_ms})
                ).fetchall()
        except ProgrammingError:
            return []
        return [
            ThroughputRow(
                ts=r.ts,
                succeeded=r.succeeded,
                errored=r.errored,
                running=r.running,
            )
            for r in rows
        ]

    async def list_schedules(self) -> list[ScheduleRow]:
        try:
            async with self.engine.connect() as conn:
                rows = (await conn.execute(text(_SCHEDULES_SQL))).fetchall()
        except ProgrammingError:
            return []
        return [
            ScheduleRow(
                schedule_id=r.schedule_id,
                schedule_name=r.schedule_name,
                workflow_name=r.workflow_name,
                workflow_class_name=r.workflow_class_name,
                schedule=r.schedule,
                status=r.status,
                last_fired_at=r.last_fired_at,
                automatic_backfill=r.automatic_backfill,
                cron_timezone=r.cron_timezone,
                queue_name=r.queue_name,
            )
            for r in rows
        ]

    async def list_queues(self) -> list[QueueRow]:
        try:
            async with self.engine.connect() as conn:
                rows = (await conn.execute(text(_QUEUES_SQL))).fetchall()
        except ProgrammingError:
            return []
        return [
            QueueRow(
                queue_id=r.queue_id,
                name=r.name,
                concurrency=r.concurrency,
                worker_concurrency=r.worker_concurrency,
                rate_limit_max=r.rate_limit_max,
                rate_limit_period_sec=r.rate_limit_period_sec,
                priority_enabled=r.priority_enabled,
                partition_queue=r.partition_queue,
                polling_interval_sec=r.polling_interval_sec,
                created_at_epoch_ms=r.created_at,
                updated_at_epoch_ms=r.updated_at,
                enqueued=r.enqueued,
                running=r.running,
            )
            for r in rows
        ]

    async def list_notifications(self, filters: NotificationFilters) -> NotificationsRows:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": filters.limit}
        if filters.consumed is not None:
            conditions.append("consumed = :consumed")
            params["consumed"] = filters.consumed
        if filters.destination_uuid:
            conditions.append("destination_uuid = :destination_uuid")
            params["destination_uuid"] = filters.destination_uuid
        if filters.topic:
            conditions.append("topic = :topic")
            params["topic"] = filters.topic
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT message_uuid, destination_uuid, topic, consumed, created_at_epoch_ms,
                   message, serialization
            FROM dbos.notifications
            {where}
            ORDER BY created_at_epoch_ms DESC
            LIMIT :limit
        """
        try:
            async with self.engine.connect() as conn:
                rows = (await conn.execute(text(sql), params)).fetchall()
                destination_ids = list({r.destination_uuid for r in rows})
                ancestor_rows = (
                    (
                        await conn.execute(
                            text(_NOTIFICATION_ANCESTORS_SQL),
                            {"destination_ids": destination_ids},
                        )
                    ).fetchall()
                    if destination_ids
                    else []
                )
        except ProgrammingError:
            return NotificationsRows(notifications=[], ancestors=[])

        notifications = [
            NotificationRow(
                message_uuid=r.message_uuid,
                destination_uuid=r.destination_uuid,
                topic=r.topic,
                consumed=r.consumed,
                created_at_epoch_ms=r.created_at_epoch_ms,
                message=r.message,
                serialization=r.serialization,
            )
            for r in rows
        ]
        ancestors = [
            AncestorRow(
                seed_id=ar.seed_id,
                workflow_uuid=ar.workflow_uuid,
                name=ar.name,
                status=ar.status,
                lvl=ar.lvl,
            )
            for ar in ancestor_rows
        ]
        return NotificationsRows(notifications=notifications, ancestors=ancestors)

    async def workflows_cursor(self) -> tuple:
        sql = """
            SELECT
                (SELECT MAX(updated_at) FROM dbos.workflow_status) AS max_updated,
                (SELECT COUNT(*) FROM dbos.workflow_status) AS wf_count,
                (SELECT COUNT(*) FROM dbos.operation_outputs) AS op_count
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_updated, row.wf_count, row.op_count)

    async def stats_cursor(self) -> tuple:
        sql = """
            SELECT
                (SELECT COUNT(*) FROM dbos.workflow_status) AS total,
                (SELECT MAX(updated_at) FROM dbos.workflow_status) AS max_updated,
                (SELECT COUNT(*) FROM dbos.notifications WHERE consumed = false) AS pending
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.total, row.max_updated, row.pending)

    async def schedules_cursor(self) -> tuple:
        sql = """
            SELECT MAX(last_fired_at) AS max_fired, COUNT(*) AS count_all
            FROM dbos.workflow_schedules
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_fired, row.count_all)

    async def queues_cursor(self) -> tuple:
        # Cursor has to advance on workflow churn too — queue *config* may not
        # change for hours, but enqueued/running counts move with every
        # send/dequeue. Both probes ride the partial in-flight index so the
        # extra cost over a queues-only cursor is negligible.
        sql = """
            SELECT
                (SELECT MAX(updated_at) FROM dbos.queues) AS max_q_updated,
                (SELECT COUNT(*) FROM dbos.queues) AS q_count,
                (SELECT MAX(updated_at) FROM dbos.workflow_status
                    WHERE queue_name IS NOT NULL
                      AND status IN ('ENQUEUED', 'PENDING')) AS max_wf_updated,
                (SELECT COUNT(*) FROM dbos.workflow_status
                    WHERE queue_name IS NOT NULL
                      AND status IN ('ENQUEUED', 'PENDING')) AS wf_count
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_q_updated, row.q_count, row.max_wf_updated, row.wf_count)

    async def notifications_cursor(self) -> tuple:
        sql = """
            SELECT
                MAX(created_at_epoch_ms) AS max_created,
                COUNT(*) AS count_all,
                COUNT(*) FILTER (WHERE consumed = false) AS count_pending
            FROM dbos.notifications
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_created, row.count_all, row.count_pending)

    async def timeseries_cursor(self) -> tuple:
        sql = """
            SELECT COUNT(*) AS count_all, MAX(created_at) AS max_created
            FROM dbos.workflow_status
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except ProgrammingError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.count_all, row.max_created)
