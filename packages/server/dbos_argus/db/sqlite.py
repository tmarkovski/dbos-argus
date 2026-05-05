"""SQLite `ArgusDB` adapter.

DBOS' SQLite system database is column-compatible with the Postgres one
(`dbos/_migration.py:sqlite_migrations`), but the SQL dialects diverge enough
that the read queries are written separately rather than templated. The
biggest deltas vs `postgres.py`:

* SQLite has no schema namespace — tables live in the main DB, no `dbos.`
  prefix.
* No array operators (`ANY`, `ARRAY[]`, `||`). For `IN (...)` we use
  SQLAlchemy expanding bindparams; for the recursive workflow tree we drop
  the in-SQL `sort_path` and run the DFS sort in Python.
* No `ILIKE` — SQLite's `LIKE` is already case-insensitive for ASCII, which
  is what our uuid/name searches need.
* No `generate_series` / `date_trunc` / `to_timestamp`. The throughput
  endpoint buckets in Python instead.
* No `information_schema`. Reflection goes through `sqlite_master` +
  `pragma_table_info`, with sqlite type strings normalized into the same
  vocabulary the packaged Postgres snapshot uses so the diff comparator can
  stay shared.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from ..schema_dump import ColumnInfo, SchemaDump, TableInfo
from ..settings import Settings
from ..workflow_status import ACTIVE_STATUSES, ERROR_STATUSES
from .base import ArgusDB
from .rows import (
    AncestorRow,
    EventRow,
    NotificationFilters,
    NotificationRow,
    NotificationsRows,
    ResultRow,
    ScheduleRow,
    StatsRow,
    StepRow,
    ThroughputRow,
    WorkflowDetailRows,
    WorkflowFamilyRow,
    WorkflowFilters,
    WorkflowListRow,
)

# Bucket → millisecond width. Buckets are aligned to UTC midnight / hour-zero
# via integer division of `created_at` (which DBOS stores as epoch ms) so we
# don't need a calendar-aware truncation.
_BUCKET_MS: dict[str, int] = {
    "hour": 3_600_000,
    "day": 86_400_000,
}


# SQLite's pragma_table_info reports the type string the migration declared.
# Normalize to the lowercase Postgres-snapshot vocabulary so `schema_diff` can
# compare them without per-dialect knowledge. Whatever isn't here is passed
# through lowercased — the diff already accepts text/character-varying as
# synonyms, and unknown types will surface as type mismatches.
_SQLITE_TYPE_NORMALIZE: dict[str, str] = {
    # SQLite INTEGER is variable-width up to 8 bytes — the same range as
    # Postgres bigint, which is what the DBOS snapshot pins for epoch-ms
    # columns. Using "bigint" keeps the diff happy on existing argus columns.
    "integer": "bigint",
    "bigint": "bigint",
    "int4": "integer",
    "text": "text",
    "boolean": "boolean",
    "numeric": "numeric",
    "real": "double precision",
    "blob": "bytea",
}


def _normalize_sqlite_type(declared: str) -> str:
    base = declared.strip().lower()
    # "varchar(255)" → "varchar"; "numeric(38,15)" → "numeric"
    paren = base.find("(")
    if paren != -1:
        base = base[:paren].rstrip()
    if base in ("varchar", "char", "character varying", "character"):
        # treat as text-equivalent (the existing diff synonym group catches this)
        return "character varying"
    return _SQLITE_TYPE_NORMALIZE.get(base, base)


def _expanding(name: str) -> bindparam:
    return bindparam(name, expanding=True)


_EMPTY_STATS = StatsRow(
    total=0,
    in_flight=0,
    enqueued=0,
    failed_recent=0,
    pending_notifications=0,
    active_schedules=0,
)


class SqliteArgusDB(ArgusDB):
    """aiosqlite-backed adapter for DBOS SQLite system databases."""

    def __init__(self, settings: Settings) -> None:
        # asyncpg-style query-arg massaging (sslmode, libpq options) is
        # Postgres-only; SQLite URLs are passed through to SQLAlchemy verbatim.
        self.engine = create_async_engine(settings.database_url, echo=False, future=True)

    @property
    def display_url(self) -> str:
        return self.engine.url.render_as_string(hide_password=True)

    async def healthcheck(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def reflect_schema(self, schema: str = "dbos") -> SchemaDump:
        async with self.engine.connect() as conn:
            table_rows = (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                        "ORDER BY name"
                    )
                )
            ).fetchall()

            tables: list[TableInfo] = []
            for tr in table_rows:
                table_name = tr[0]
                # PRAGMA can't be parameterized; the table name comes from
                # sqlite_master so it's safe to interpolate.
                col_rows = (
                    await conn.execute(text(f"PRAGMA table_info('{table_name}')"))
                ).fetchall()
                columns = tuple(
                    ColumnInfo(
                        name=cr[1],
                        data_type=_normalize_sqlite_type(cr[2] or ""),
                    )
                    for cr in col_rows
                )
                tables.append(TableInfo(name=table_name, columns=columns))

        # `schema` is echoed back so the diff against the Postgres snapshot
        # can match `expected.schema == "dbos"`. SQLite has no namespace, so
        # the value is decorative.
        return SchemaDump(schema=schema, tables=tuple(tables))

    async def list_workflows(self, filters: WorkflowFilters) -> list[WorkflowListRow]:
        try:
            async with self.engine.connect() as conn:
                rows = await self._list_workflows(conn, filters)
        except OperationalError:
            return []
        return rows

    async def _list_workflows(
        self, conn: AsyncConnection, filters: WorkflowFilters
    ) -> list[WorkflowListRow]:
        # Build the same root-conditions set the Postgres adapter uses.
        params: dict[str, object] = {"limit": filters.limit}
        root_conditions: list[str] = []

        if filters.started_after_ms is not None:
            root_conditions.append("COALESCE(started_at_epoch_ms, created_at) >= :started_after_ms")
            params["started_after_ms"] = filters.started_after_ms
        if filters.started_before_ms is not None:
            root_conditions.append(
                "COALESCE(started_at_epoch_ms, created_at) <= :started_before_ms"
            )
            params["started_before_ms"] = filters.started_before_ms

        statuses_bind = None
        if filters.statuses:
            root_conditions.append("status IN :statuses")
            params["statuses"] = filters.statuses
            statuses_bind = _expanding("statuses")
        else:
            root_conditions.append("status <> 'ENQUEUED'")

        if filters.queue_name:
            root_conditions.append("queue_name = :queue_name")
            params["queue_name"] = filters.queue_name
        if filters.hide_scheduled:
            root_conditions.append("workflow_uuid NOT LIKE 'sched-%'")

        has_q = bool(filters.q)
        if has_q:
            params["q_pat"] = f"%{filters.q}%"

        where_extra = (" AND " + " AND ".join(root_conditions)) if root_conditions else ""

        if filters.grouped:
            if has_q:
                # Find any workflow matching `q`, walk up to its root, include
                # the root's whole subtree below — same pattern as Postgres.
                match_ctes = """
                    upward AS (
                        SELECT workflow_uuid, parent_workflow_id
                        FROM workflow_status
                        WHERE workflow_uuid LIKE :q_pat OR name LIKE :q_pat
                        UNION
                        SELECT ws.workflow_uuid, ws.parent_workflow_id
                        FROM workflow_status ws
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
                        FROM workflow_status
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
                            0 AS depth,
                            r.updated_at AS root_updated_at,
                            ws.workflow_uuid AS root_uuid
                        FROM workflow_status ws
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
                            t.depth + 1,
                            t.root_updated_at,
                            t.root_uuid
                        FROM workflow_status c
                        JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
                    )
                SELECT
                    t.workflow_uuid, t.parent_workflow_id, t.name, t.status,
                    t.queue_name, t.executor_id, t.priority,
                    t.started_ms, t.updated_ms, t.depth,
                    t.root_updated_at, t.root_uuid,
                    COALESCE(oc.op_count, 0) AS op_count
                FROM tree t
                LEFT JOIN (
                    SELECT workflow_uuid, COUNT(*) AS op_count
                    FROM operation_outputs
                    WHERE workflow_uuid IN (SELECT workflow_uuid FROM tree)
                    GROUP BY workflow_uuid
                ) oc ON oc.workflow_uuid = t.workflow_uuid
            """
            stmt = text(sql)
            if statuses_bind is not None:
                stmt = stmt.bindparams(statuses_bind)
            rows = (await conn.execute(stmt, params)).fetchall()

            # Postgres uses `ORDER BY root_updated_at DESC, sort_path ASC` to
            # produce a DFS layout. SQLite has no array sort, so we sort here
            # in Python: group rows by root, order roots by root_updated_at
            # DESC, then DFS within each root by started_ms.
            return _dfs_grouped(rows)

        # Flat mode — same conditions, no recursion, ordered by started DESC.
        flat_conditions = list(root_conditions)
        if has_q:
            flat_conditions.append("(workflow_uuid LIKE :q_pat OR name LIKE :q_pat)")
        flat_where_extra = " AND " + " AND ".join(flat_conditions) if flat_conditions else ""
        flat_where = f"WHERE 1=1{flat_where_extra}" if flat_where_extra else ""
        sql = f"""
            WITH chosen AS (
                SELECT
                    workflow_uuid, parent_workflow_id, name, status, queue_name, executor_id,
                    priority,
                    COALESCE(started_at_epoch_ms, created_at) AS started_ms,
                    updated_at AS updated_ms
                FROM workflow_status
                {flat_where}
                ORDER BY COALESCE(started_at_epoch_ms, created_at) DESC
                LIMIT :limit
            )
            SELECT
                c.workflow_uuid, c.parent_workflow_id, c.name, c.status,
                c.queue_name, c.executor_id, c.priority,
                c.started_ms, c.updated_ms,
                0 AS depth,
                COALESCE(oc.op_count, 0) AS op_count
            FROM chosen c
            LEFT JOIN (
                SELECT workflow_uuid, COUNT(*) AS op_count
                FROM operation_outputs
                WHERE workflow_uuid IN (SELECT workflow_uuid FROM chosen)
                GROUP BY workflow_uuid
            ) oc ON oc.workflow_uuid = c.workflow_uuid
            ORDER BY c.started_ms DESC
        """
        stmt = text(sql)
        if statuses_bind is not None:
            stmt = stmt.bindparams(statuses_bind)
        rows = (await conn.execute(stmt, params)).fetchall()
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
                depth=r.depth,
                op_count=r.op_count,
            )
            for r in rows
        ]

    async def get_workflow_detail(self, workflow_id: str) -> WorkflowDetailRows:
        try:
            async with self.engine.connect() as conn:
                family_rows_raw = (
                    await conn.execute(
                        text(
                            """
                            WITH RECURSIVE
                                up AS (
                                    SELECT workflow_uuid, parent_workflow_id, 0 AS lvl
                                    FROM workflow_status
                                    WHERE workflow_uuid = :workflow_id

                                    UNION ALL

                                    SELECT ws.workflow_uuid, ws.parent_workflow_id, u.lvl + 1
                                    FROM workflow_status ws
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
                                        ws.recovery_attempts,
                                        ws.workflow_timeout_ms,
                                        ws.output IS NOT NULL AS has_output,
                                        ws.error IS NOT NULL AS has_error,
                                        COALESCE(ws.started_at_epoch_ms, ws.created_at)
                                            AS started_ms,
                                        ws.updated_at AS updated_ms,
                                        0 AS depth
                                    FROM workflow_status ws
                                    JOIN root r ON ws.workflow_uuid = r.workflow_uuid

                                    UNION ALL

                                    SELECT
                                        c.workflow_uuid,
                                        c.parent_workflow_id,
                                        c.name,
                                        c.status,
                                        c.queue_name,
                                        c.executor_id,
                                        c.recovery_attempts,
                                        c.workflow_timeout_ms,
                                        c.output IS NOT NULL,
                                        c.error IS NOT NULL,
                                        COALESCE(c.started_at_epoch_ms, c.created_at),
                                        c.updated_at,
                                        t.depth + 1
                                    FROM workflow_status c
                                    JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
                                )
                            SELECT * FROM tree
                            """
                        ),
                        {"workflow_id": workflow_id},
                    )
                ).fetchall()

                family_sorted = _dfs_family(family_rows_raw)
                family_ids = [r.workflow_uuid for r in family_sorted]

                if not family_ids:
                    return WorkflowDetailRows(family=[], steps=[], events=[])

                steps_stmt = text(
                    """
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
                        CASE WHEN o.function_name = 'DBOS.sleep' THEN o.output END
                            AS sleep_output_raw
                    FROM operation_outputs o
                    LEFT JOIN workflow_events_history seh
                        ON o.function_name = 'DBOS.setEvent'
                        AND seh.workflow_uuid = o.workflow_uuid
                        AND seh.function_id = o.function_id
                    WHERE o.workflow_uuid IN :workflow_ids
                    ORDER BY o.workflow_uuid, o.function_id ASC
                    """
                ).bindparams(_expanding("workflow_ids"))
                step_rows = (
                    await conn.execute(steps_stmt, {"workflow_ids": family_ids})
                ).fetchall()

                events_stmt = text(
                    """
                    SELECT
                        we.workflow_uuid,
                        we.key,
                        we.value AS current_value,
                        we.serialization AS current_serialization,
                        weh.function_id,
                        weh.value AS history_value,
                        weh.serialization AS history_serialization,
                        o.completed_at_epoch_ms
                    FROM workflow_events we
                    LEFT JOIN workflow_events_history weh
                        ON weh.workflow_uuid = we.workflow_uuid AND weh.key = we.key
                    LEFT JOIN operation_outputs o
                        ON o.workflow_uuid = weh.workflow_uuid
                            AND o.function_id = weh.function_id
                    WHERE we.workflow_uuid IN :workflow_ids
                    ORDER BY we.workflow_uuid, we.key, weh.function_id ASC
                    """
                ).bindparams(_expanding("workflow_ids"))
                event_rows = (
                    await conn.execute(events_stmt, {"workflow_ids": family_ids})
                ).fetchall()
        except OperationalError:
            return WorkflowDetailRows(family=[], steps=[], events=[])

        family = [
            WorkflowFamilyRow(
                workflow_uuid=r.workflow_uuid,
                parent_workflow_id=r.parent_workflow_id,
                name=r.name,
                status=r.status,
                queue_name=r.queue_name,
                executor_id=r.executor_id,
                recovery_attempts=r.recovery_attempts,
                workflow_timeout_ms=r.workflow_timeout_ms,
                has_output=bool(r.has_output),
                has_error=bool(r.has_error),
                started_ms=r.started_ms,
                updated_ms=r.updated_ms,
                depth=r.depth,
            )
            for r in family_sorted
        ]
        steps = [
            StepRow(
                workflow_uuid=s.workflow_uuid,
                function_id=s.function_id,
                function_name=s.function_name,
                has_output=bool(s.has_output),
                has_error=bool(s.has_error),
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
                    await conn.execute(
                        text(
                            "SELECT output, error, serialization FROM workflow_status "
                            "WHERE workflow_uuid = :workflow_id"
                        ),
                        {"workflow_id": workflow_id},
                    )
                ).fetchone()
        except OperationalError:
            return None
        if row is None:
            return None
        return ResultRow(output=row.output, error=row.error, serialization=row.serialization)

    async def get_step_result(self, workflow_id: str, function_id: int) -> ResultRow | None:
        try:
            async with self.engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT output, error, serialization FROM operation_outputs "
                            "WHERE workflow_uuid = :workflow_id AND function_id = :function_id"
                        ),
                        {"workflow_id": workflow_id, "function_id": function_id},
                    )
                ).fetchone()
        except OperationalError:
            return None
        if row is None:
            return None
        return ResultRow(output=row.output, error=row.error, serialization=row.serialization)

    async def get_stats(self, since_ms: int) -> StatsRow:
        try:
            async with self.engine.connect() as conn:
                # Each subquery uses an IN with an expanding bindparam. Names
                # have to differ across binds (SQLAlchemy can't reuse the same
                # expanding name in one statement).
                stmt = text(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM workflow_status)
                            AS total,
                        (SELECT COUNT(*) FROM workflow_status WHERE status IN :active_a)
                            AS in_flight,
                        (SELECT COUNT(*) FROM workflow_status WHERE status = 'ENQUEUED')
                            AS enqueued,
                        (SELECT COUNT(*) FROM workflow_status
                            WHERE status IN :error_a
                            AND COALESCE(started_at_epoch_ms, created_at) >= :since_ms)
                            AS failed_recent,
                        (SELECT COUNT(*) FROM notifications WHERE consumed = 0)
                            AS pending_notifications,
                        (SELECT COUNT(*) FROM workflow_schedules WHERE status = 'ACTIVE')
                            AS active_schedules
                    """
                ).bindparams(_expanding("active_a"), _expanding("error_a"))
                row = (
                    await conn.execute(
                        stmt,
                        {
                            "active_a": list(ACTIVE_STATUSES),
                            "error_a": list(ERROR_STATUSES),
                            "since_ms": since_ms,
                        },
                    )
                ).fetchone()
        except OperationalError:
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
        )

    async def get_throughput(
        self, since_ms: int, until_ms: int, bucket: Literal["hour", "day"]
    ) -> list[ThroughputRow]:
        bucket_ms = _BUCKET_MS[bucket]
        try:
            async with self.engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT created_at, status FROM workflow_status "
                            "WHERE created_at >= :s AND created_at <= :u"
                        ),
                        {"s": since_ms, "u": until_ms},
                    )
                ).fetchall()
        except OperationalError:
            return []

        # Bucket the rows in Python — keeps the SQL portable and skips the
        # generate_series / date_trunc apparatus we'd otherwise need.
        counts: dict[int, dict[str, int]] = defaultdict(
            lambda: {"succeeded": 0, "errored": 0, "running": 0}
        )
        for r in rows:
            b = (r.created_at // bucket_ms) * bucket_ms
            if r.status == "SUCCESS":
                counts[b]["succeeded"] += 1
            elif r.status in ERROR_STATUSES:
                counts[b]["errored"] += 1
            elif r.status in ACTIVE_STATUSES:
                counts[b]["running"] += 1

        # Emit a contiguous bucket sequence (zero-filling empties) so the
        # client gets a complete time axis even on quiet windows.
        first = (since_ms // bucket_ms) * bucket_ms
        last = (until_ms // bucket_ms) * bucket_ms
        result: list[ThroughputRow] = []
        b = first
        while b <= last:
            c = counts.get(b, {"succeeded": 0, "errored": 0, "running": 0})
            result.append(
                ThroughputRow(
                    ts=datetime.fromtimestamp(b / 1000, tz=UTC),
                    succeeded=c["succeeded"],
                    errored=c["errored"],
                    running=c["running"],
                )
            )
            b += bucket_ms
        return result

    async def list_schedules(self) -> list[ScheduleRow]:
        try:
            async with self.engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                schedule_id, schedule_name, workflow_name, workflow_class_name,
                                schedule, status, last_fired_at, automatic_backfill,
                                cron_timezone, queue_name
                            FROM workflow_schedules
                            ORDER BY schedule_name ASC
                            """
                        )
                    )
                ).fetchall()
        except OperationalError:
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
                automatic_backfill=bool(r.automatic_backfill),
                cron_timezone=r.cron_timezone,
                queue_name=r.queue_name,
            )
            for r in rows
        ]

    async def list_notifications(self, filters: NotificationFilters) -> NotificationsRows:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": filters.limit}
        if filters.consumed is not None:
            conditions.append("consumed = :consumed")
            # SQLite booleans are 0/1; pass through the int form so the
            # comparison works regardless of dialect-level coercion.
            params["consumed"] = 1 if filters.consumed else 0
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
            FROM notifications
            {where}
            ORDER BY created_at_epoch_ms DESC
            LIMIT :limit
        """
        try:
            async with self.engine.connect() as conn:
                rows = (await conn.execute(text(sql), params)).fetchall()
                destination_ids = list({r.destination_uuid for r in rows})
                ancestor_rows = []
                if destination_ids:
                    ancestors_stmt = text(
                        """
                        WITH RECURSIVE up AS (
                            SELECT
                                ws.workflow_uuid AS seed_id,
                                ws.workflow_uuid,
                                ws.parent_workflow_id,
                                ws.name,
                                ws.status,
                                0 AS lvl
                            FROM workflow_status ws
                            WHERE ws.workflow_uuid IN :destination_ids

                            UNION ALL

                            SELECT
                                u.seed_id,
                                ws.workflow_uuid,
                                ws.parent_workflow_id,
                                ws.name,
                                ws.status,
                                u.lvl + 1
                            FROM workflow_status ws
                            JOIN up u ON ws.workflow_uuid = u.parent_workflow_id
                        )
                        SELECT seed_id, workflow_uuid, name, status, lvl
                        FROM up
                        ORDER BY seed_id, lvl DESC
                        """
                    ).bindparams(_expanding("destination_ids"))
                    ancestor_rows = (
                        await conn.execute(ancestors_stmt, {"destination_ids": destination_ids})
                    ).fetchall()
        except OperationalError:
            return NotificationsRows(notifications=[], ancestors=[])

        notifications = [
            NotificationRow(
                message_uuid=r.message_uuid,
                destination_uuid=r.destination_uuid,
                topic=r.topic,
                consumed=bool(r.consumed),
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
                (SELECT MAX(updated_at) FROM workflow_status) AS max_updated,
                (SELECT COUNT(*) FROM workflow_status) AS wf_count,
                (SELECT COUNT(*) FROM operation_outputs) AS op_count
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except OperationalError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_updated, row.wf_count, row.op_count)

    async def stats_cursor(self) -> tuple:
        sql = """
            SELECT
                (SELECT COUNT(*) FROM workflow_status) AS total,
                (SELECT MAX(updated_at) FROM workflow_status) AS max_updated,
                (SELECT COUNT(*) FROM notifications WHERE consumed = 0) AS pending
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except OperationalError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.total, row.max_updated, row.pending)

    async def schedules_cursor(self) -> tuple:
        sql = """
            SELECT MAX(last_fired_at) AS max_fired, COUNT(*) AS count_all
            FROM workflow_schedules
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except OperationalError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.max_fired, row.count_all)

    async def notifications_cursor(self) -> tuple:
        # SQLite has no FILTER (WHERE …) clause; fold into a CASE SUM.
        sql = """
            SELECT
                MAX(created_at_epoch_ms) AS max_created,
                COUNT(*) AS count_all,
                SUM(CASE WHEN consumed = 0 THEN 1 ELSE 0 END) AS count_pending
            FROM notifications
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except OperationalError:
            return ("empty",)
        if row is None:
            return ("empty",)
        # SUM over no rows is NULL in SQLite; coerce to 0 for a clean tuple.
        return (row.max_created, row.count_all, row.count_pending or 0)

    async def timeseries_cursor(self) -> tuple:
        sql = """
            SELECT COUNT(*) AS count_all, MAX(created_at) AS max_created
            FROM workflow_status
        """
        try:
            async with self.engine.connect() as conn:
                row = (await conn.execute(text(sql))).fetchone()
        except OperationalError:
            return ("empty",)
        if row is None:
            return ("empty",)
        return (row.count_all, row.max_created)


def _dfs_grouped(rows) -> list[WorkflowListRow]:
    """Convert flat (parent_id, root_uuid, root_updated_at, depth, …) rows
    from the recursive grouped query into a DFS-ordered list — same layout
    the Postgres query emits via `ORDER BY root_updated_at DESC, sort_path`."""
    # Group by root, sort roots by root_updated_at DESC.
    by_root: dict[str, dict[str, object]] = {}
    for r in rows:
        rec = by_root.setdefault(
            r.root_uuid,
            {"root_updated_at": r.root_updated_at, "rows": []},
        )
        rec["rows"].append(r)
    sorted_roots = sorted(
        by_root.values(),
        key=lambda v: v["root_updated_at"],
        reverse=True,
    )

    out: list[WorkflowListRow] = []
    for rec in sorted_roots:
        out.extend(_dfs_in_group(rec["rows"]))
    return out


def _dfs_in_group(rows) -> list[WorkflowListRow]:
    """DFS over a single root's subtree, ordered by started_ms within
    siblings to match the Postgres `sort_path` layout."""
    children: dict[str | None, list] = defaultdict(list)
    self_row: dict[str, object] = {}
    root_uuid = None
    for r in rows:
        self_row[r.workflow_uuid] = r
        if r.depth == 0:
            root_uuid = r.workflow_uuid
        else:
            children[r.parent_workflow_id].append(r)
    for kids in children.values():
        kids.sort(key=lambda c: c.started_ms)

    if root_uuid is None:
        return []

    out: list[WorkflowListRow] = []
    stack = [self_row[root_uuid]]
    while stack:
        cur = stack.pop()
        out.append(_to_workflow_list_row(cur))
        kids = children.get(cur.workflow_uuid, [])
        # push reversed so leftmost child is processed first
        for k in reversed(kids):
            stack.append(k)
    return out


def _to_workflow_list_row(r) -> WorkflowListRow:
    return WorkflowListRow(
        workflow_uuid=r.workflow_uuid,
        parent_workflow_id=r.parent_workflow_id,
        name=r.name,
        status=r.status,
        queue_name=r.queue_name,
        executor_id=r.executor_id,
        priority=r.priority,
        started_ms=r.started_ms,
        updated_ms=r.updated_ms,
        depth=r.depth,
        op_count=r.op_count,
    )


def _dfs_family(rows) -> list:
    """DFS the workflow_detail family rows by started_ms within siblings.
    Returns the rows themselves (not yet mapped to dataclasses) so the caller
    can build `WorkflowFamilyRow`s and pluck `family_ids` in one pass."""
    if not rows:
        return []
    children: dict[str | None, list] = defaultdict(list)
    by_uuid: dict[str, object] = {}
    root = None
    for r in rows:
        by_uuid[r.workflow_uuid] = r
        if r.depth == 0:
            root = r
        else:
            children[r.parent_workflow_id].append(r)
    for kids in children.values():
        kids.sort(key=lambda c: c.started_ms)

    if root is None:
        return []
    out = []
    stack = [root]
    while stack:
        cur = stack.pop()
        out.append(cur)
        for k in reversed(children.get(cur.workflow_uuid, [])):
            stack.append(k)
    return out
