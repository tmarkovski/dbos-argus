import logging
import os
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from . import __version__
from .db import db
from .db.rows import (
    NotificationFilters,
    NotificationsRows,
    QueueRow,
    ScheduleRow,
    StatsRow,
    StepRow,
    ThroughputRow,
    WorkflowDetailRows,
    WorkflowFilters,
    WorkflowListRow,
)
from .decoding import decode_dbos_value
from .schema_dump import load_full_dump
from .settings import settings
from .sql_diagnostics import inspect_dbos_schema

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("dbos_argus")


class _HealthzAccessFilter(logging.Filter):
    """Drop uvicorn access-log lines for /healthz.

    The console polls /healthz every 5s for the DB connection indicator —
    without this the access log is mostly healthz spam. Real failures still
    surface via the response body (`database: down`) and any uncaught error
    is logged separately by uvicorn's error logger.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = args[2]
        return not (isinstance(path, str) and path.startswith("/healthz"))


logging.getLogger("uvicorn.access").addFilter(_HealthzAccessFilter())

app = FastAPI(
    title="dbos-argus",
    version=__version__,
    description="Self-hosted, read-only workflow viewer for DBOS Transact.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Realtime layer wiring is below the route bodies — channels lazy-import the
# `fetch_*` helpers above to break the circular dep with this module.
def _setup_realtime() -> None:
    if not settings.realtime_enabled:
        logger.info("realtime layer disabled (ARGUS_REALTIME_ENABLED=false)")
        return
    from .realtime import RealtimeHub, register_websocket_route
    from .realtime.channels import (
        HealthChannel,
        NotificationsChannel,
        QueuesChannel,
        SchedulesChannel,
        StatsChannel,
        StatsTimeseriesChannel,
        WorkflowChannel,
        WorkflowsChannel,
    )

    hub = RealtimeHub(
        default_interval_ms=settings.realtime_interval_ms,
        max_subs_per_conn=settings.realtime_max_subs_per_conn,
    )
    hub.register_channel(HealthChannel(), interval_ms=settings.realtime_health_interval_ms)
    hub.register_channel(StatsChannel())
    hub.register_channel(StatsTimeseriesChannel())
    hub.register_channel(WorkflowsChannel())
    hub.register_channel(WorkflowChannel())
    hub.register_channel(SchedulesChannel())
    hub.register_channel(QueuesChannel())
    hub.register_channel(NotificationsChannel())
    register_websocket_route(app, hub, allowed_origins=settings.cors_origins_list)
    app.state.realtime_hub = hub


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    db_up = True
    db_error: str | None = None
    try:
        await db.healthcheck()
    except Exception as e:
        db_up = False
        db_error = str(e)
    body: dict[str, str] = {
        "status": "ok" if db_up else "degraded",
        "database": "up" if db_up else "down",
        "database_url": db.display_url,
        "database_dialect": db.dialect,
    }
    if db_up:
        version = await db.server_version()
        if version is not None:
            body["database_version"] = version
        rev = await db.dbos_schema_revision()
        if rev is not None:
            body["dbos_schema_revision"] = str(rev)
    if db_error is not None:
        body["database_error"] = db_error
    return body


@app.get("/version")
async def version() -> dict[str, str]:
    # tested_dbos_version is sourced from the packaged schema snapshot —
    # whichever DBOS version produced the dbos.* schema this build was
    # validated against. The CI watchdog refreshes the snapshot on each
    # DBOS release, so this is automatically what `git log` would show.
    snapshot = load_full_dump()
    return {
        "version": __version__,
        "tested_dbos_version": str(snapshot.meta.get("dbos_version", "unknown")),
    }


class SqlDiagnosticIssue(BaseModel):
    kind: Literal["missing_table", "missing_column", "wrong_type"]
    table_name: str
    column_name: str | None
    expected_type: str | None
    actual_type: str | None
    detail: str


class SqlDiagnostics(BaseModel):
    ok: bool
    issues: list[SqlDiagnosticIssue]


@app.get("/api/sql-diagnostics")
async def get_sql_diagnostics() -> SqlDiagnostics:
    try:
        issues = await inspect_dbos_schema(db)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=503, detail="database diagnostics unavailable") from e
    return SqlDiagnostics(
        ok=not issues,
        issues=[
            SqlDiagnosticIssue(
                kind=issue.kind,
                table_name=issue.table_name,
                column_name=issue.column_name,
                expected_type=issue.expected_type,
                actual_type=issue.actual_type,
                detail=issue.detail,
            )
            for issue in issues
        ],
    )


class WorkflowListItem(BaseModel):
    workflow_id: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    queue_name: str | None
    executor_id: str | None
    # DBOS queue priority — lower runs first. Defaults to 0 when unset.
    priority: int
    started_at: datetime
    updated_at: datetime
    depth: int
    # Number of dbos.operation_outputs rows for this workflow. Computed via
    # SQL COUNT — the list endpoint never materialises individual operations.
    operation_count: int


# Pure mapper from a list-row dataclass to the public Pydantic model. Shared
# by the REST route and the realtime `workflows` channel so the wire shape
# stays identical across transports.
def _to_workflow_list_item(r: WorkflowListRow) -> WorkflowListItem:
    return WorkflowListItem(
        workflow_id=r.workflow_uuid,
        parent_workflow_id=r.parent_workflow_id,
        name=r.name,
        status=r.status,
        queue_name=r.queue_name,
        executor_id=r.executor_id,
        priority=r.priority or 0,
        started_at=datetime.fromtimestamp(r.started_ms / 1000, tz=UTC),
        updated_at=datetime.fromtimestamp(r.updated_ms / 1000, tz=UTC),
        depth=r.depth,
        operation_count=r.op_count,
    )


async def fetch_workflow_list(filters: WorkflowFilters) -> list[WorkflowListItem]:
    """Run the workflow-list query and return Pydantic models. Used by the
    REST route and the realtime channel."""
    rows = await db.list_workflows(filters)
    return [_to_workflow_list_item(r) for r in rows]


@app.get("/api/workflows")
async def list_workflows(
    limit: int = Query(default=50, ge=1, le=200),
    q: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    queue_name: str | None = None,
    grouped: bool = True,
    hide_scheduled: bool = False,
) -> list[WorkflowListItem]:
    filters = WorkflowFilters(
        limit=limit,
        q=q.strip() if q else None,
        started_after_ms=int(started_after.timestamp() * 1000) if started_after else None,
        started_before_ms=int(started_before.timestamp() * 1000) if started_before else None,
        statuses=status if status else None,
        queue_name=queue_name,
        hide_scheduled=hide_scheduled,
        grouped=grouped,
    )
    return await fetch_workflow_list(filters)


class WorkflowStep(BaseModel):
    # Which workflow in the family this step belongs to.
    workflow_id: str
    function_id: int
    function_name: str
    # Whether the row stored an output / error payload. The actual content
    # is fetched lazily via /api/workflows/{id}/steps/{function_id}/result —
    # outputs can be large pickled blobs we don't want on every list render.
    has_output: bool
    has_error: bool
    child_workflow_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    # For `DBOS.setEvent` rows, the event key — joined from
    # `dbos.workflow_events_history` on `(workflow_uuid, function_id)`. Always
    # null for `DBOS.getEvent` because DBOS doesn't persist the call's input
    # args (target workflow id + key) anywhere queryable, and we refuse to
    # guess. The getEvent's deserialized value is in the lazy result endpoint.
    event_key: str | None
    # For `DBOS.sleep` rows only. The originally-requested duration in ms,
    # derived from `output` (unix wakeup seconds) - `started_at`. Computed
    # server-side so we don't have to ship the raw output column.
    sleep_requested_ms: int | None


# Detail-page version of a workflow row. Drops the inheritance from
# WorkflowListItem because the detail endpoint doesn't compute operation_count
# (steps are returned alongside, clients count from the steps array if they
# need it). Carries flags instead of payloads — the result endpoint serves
# the actual output/error.
class WorkflowFamilyItem(BaseModel):
    workflow_id: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    queue_name: str | None
    executor_id: str | None
    # Number of times this workflow was resumed after an executor crash.
    # 0 on a clean first run; > 0 means at least one recovery happened.
    recovery_attempts: int | None
    # Configured timeout in ms (workflow_status.workflow_timeout_ms). None
    # when no timeout was set on the workflow.
    workflow_timeout_ms: int | None
    started_at: datetime
    updated_at: datetime
    depth: int
    has_output: bool
    has_error: bool


class EventSet(BaseModel):
    function_id: int
    value: str
    serialization: str | None
    value_decoded: str | None
    completed_at: datetime | None


class WorkflowEventEntry(BaseModel):
    workflow_id: str
    key: str
    # Current value (from `dbos.workflow_events`). Same as the most recent
    # entry in `history`; surfaced separately because that's what readers see.
    value: str
    serialization: str | None
    value_decoded: str | None
    # Every `setEvent(key, …)` call for this key on this workflow, ordered by
    # function_id ASC (call order). One entry on first set; multiple entries
    # when the workflow re-set the same key.
    history: list[EventSet]


class WorkflowDetail(BaseModel):
    workflow_id: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    started_at: datetime
    updated_at: datetime
    # Entire workflow family rooted at the topmost ancestor, in DFS order
    # (same shape & ordering as the grouped list endpoint). Single-entry
    # when the workflow has no parent and no children.
    family: list[WorkflowFamilyItem]
    # Steps (dbos.operation_outputs rows) for every workflow in `family`,
    # ordered by (workflow_id, function_id ASC). Clients group by
    # workflow_id to build per-workflow timelines.
    steps: list[WorkflowStep]
    # Events published by any workflow in the family via `DBOS.setEvent`.
    # Bundled here (rather than lazy-loaded) because they're typically few
    # per workflow and shown immediately on selection.
    events: list[WorkflowEventEntry]


class WorkflowResult(BaseModel):
    workflow_id: str
    output: str | None
    error: str | None
    serialization: str | None
    # Best-effort pretty-printed JSON of the decoded output/error. None when
    # the payload wasn't decodable — e.g. pickled custom classes which our
    # restricted unpickler refuses to instantiate. See decoding.py.
    output_decoded: str | None
    error_decoded: str | None


class StepResult(BaseModel):
    workflow_id: str
    function_id: int
    output: str | None
    error: str | None
    serialization: str | None
    output_decoded: str | None
    error_decoded: str | None


# DBOS.sleep rows store their wakeup time as a numeric string in `output`
# (unix seconds, JSON-encoded even under py_pickle serialization). Subtracting
# the row's `started_at` gives the originally requested duration in ms,
# independent of how long the sleep actually elapsed in wall time. Returns
# None for non-sleep rows or when the value isn't parseable as a float.
def _sleep_requested_ms(step: StepRow) -> int | None:
    if (
        step.function_name != "DBOS.sleep"
        or not step.sleep_output_raw
        or step.started_at_epoch_ms is None
    ):
        return None
    try:
        wake_ms = float(step.sleep_output_raw) * 1000
    except (TypeError, ValueError):
        return None
    requested = round(wake_ms - step.started_at_epoch_ms)
    return int(requested) if requested >= 0 else None


# Walks up parent_workflow_id to find the topmost ancestor (or the workflow
# itself if it has no parent), then expands that ancestor's whole subtree in
# DFS order — matching how the list endpoint groups trees.
def _build_workflow_detail(detail: WorkflowDetailRows, workflow_id: str) -> WorkflowDetail | None:
    """Map adapter rows to the detail Pydantic model. Returns None when the
    family is empty (workflow not found) — callers translate that to a 404
    or an empty snapshot, depending on transport."""
    if not detail.family:
        return None

    family = [
        WorkflowFamilyItem(
            workflow_id=r.workflow_uuid,
            parent_workflow_id=r.parent_workflow_id,
            name=r.name,
            status=r.status,
            queue_name=r.queue_name,
            executor_id=r.executor_id,
            recovery_attempts=r.recovery_attempts,
            workflow_timeout_ms=r.workflow_timeout_ms,
            has_output=r.has_output,
            has_error=r.has_error,
            started_at=datetime.fromtimestamp(r.started_ms / 1000, tz=UTC),
            updated_at=datetime.fromtimestamp(r.updated_ms / 1000, tz=UTC),
            depth=r.depth,
        )
        for r in detail.family
    ]
    steps = [
        WorkflowStep(
            workflow_id=s.workflow_uuid,
            function_id=s.function_id,
            function_name=s.function_name,
            has_output=s.has_output,
            has_error=s.has_error,
            child_workflow_id=s.child_workflow_id,
            started_at=(
                datetime.fromtimestamp(s.started_at_epoch_ms / 1000, tz=UTC)
                if s.started_at_epoch_ms is not None
                else None
            ),
            completed_at=(
                datetime.fromtimestamp(s.completed_at_epoch_ms / 1000, tz=UTC)
                if s.completed_at_epoch_ms is not None
                else None
            ),
            event_key=s.event_key,
            sleep_requested_ms=_sleep_requested_ms(s),
        )
        for s in detail.steps
    ]

    # Group event rows by (workflow_uuid, key); each group becomes one entry
    # whose `value` is the current row from `workflow_events` and whose
    # `history` is the per-call `workflow_events_history` rows in call order.
    events_by_key: dict[tuple[str, str], WorkflowEventEntry] = {}
    for e in detail.events:
        gk = (e.workflow_uuid, e.key)
        entry = events_by_key.get(gk)
        if entry is None:
            entry = WorkflowEventEntry(
                workflow_id=e.workflow_uuid,
                key=e.key,
                value=e.current_value,
                serialization=e.current_serialization,
                value_decoded=decode_dbos_value(e.current_value, e.current_serialization),
                history=[],
            )
            events_by_key[gk] = entry
        if e.function_id is not None:
            entry.history.append(
                EventSet(
                    function_id=e.function_id,
                    value=e.history_value,
                    serialization=e.history_serialization,
                    value_decoded=decode_dbos_value(e.history_value, e.history_serialization),
                    completed_at=(
                        datetime.fromtimestamp(e.completed_at_epoch_ms / 1000, tz=UTC)
                        if e.completed_at_epoch_ms is not None
                        else None
                    ),
                )
            )
    events = list(events_by_key.values())

    self_item = next((w for w in family if w.workflow_id == workflow_id), None)
    if self_item is None:
        return None
    return WorkflowDetail(
        workflow_id=self_item.workflow_id,
        parent_workflow_id=self_item.parent_workflow_id,
        name=self_item.name,
        status=self_item.status,
        started_at=self_item.started_at,
        updated_at=self_item.updated_at,
        family=family,
        steps=steps,
        events=events,
    )


async def fetch_workflow_detail(workflow_id: str) -> WorkflowDetail | None:
    """Run the workflow-detail query and map to the Pydantic model. Returns
    None when the workflow doesn't exist."""
    detail = await db.get_workflow_detail(workflow_id)
    return _build_workflow_detail(detail, workflow_id)


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> WorkflowDetail:
    result = await fetch_workflow_detail(workflow_id)
    if result is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return result


# Lazily fetches the output/error payload for a single workflow row. Split out
# from the detail endpoint so workflow detail page loads stay small even when
# a family contains many workflows with multi-MB pickled outputs.
@app.get("/api/workflows/{workflow_id}/result")
async def get_workflow_result(workflow_id: str) -> WorkflowResult:
    row = await db.get_workflow_result(workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return WorkflowResult(
        workflow_id=workflow_id,
        output=row.output,
        error=row.error,
        serialization=row.serialization,
        output_decoded=decode_dbos_value(row.output, row.serialization),
        error_decoded=decode_dbos_value(row.error, row.serialization),
    )


# Lazily fetches a single step row's output/error. Companion to the workflow
# result endpoint — same lazy-load pattern, indexed by (workflow_uuid, function_id).
@app.get("/api/workflows/{workflow_id}/steps/{function_id}/result")
async def get_step_result(workflow_id: str, function_id: int) -> StepResult:
    row = await db.get_step_result(workflow_id, function_id)
    if row is None:
        raise HTTPException(status_code=404, detail="step not found")
    return StepResult(
        workflow_id=workflow_id,
        function_id=function_id,
        output=row.output,
        error=row.error,
        serialization=row.serialization,
        output_decoded=decode_dbos_value(row.output, row.serialization),
        error_decoded=decode_dbos_value(row.error, row.serialization),
    )


class DashboardStats(BaseModel):
    total: int
    in_flight: int
    enqueued: int
    failed_recent: int
    pending_notifications: int
    active_schedules: int
    total_queues: int


def _to_dashboard_stats(row: StatsRow) -> DashboardStats:
    return DashboardStats(
        total=row.total,
        in_flight=row.in_flight,
        enqueued=row.enqueued,
        failed_recent=row.failed_recent,
        pending_notifications=row.pending_notifications,
        active_schedules=row.active_schedules,
        total_queues=row.total_queues,
    )


async def fetch_stats() -> DashboardStats:
    since_ms = int(datetime.now(UTC).timestamp() * 1000) - 86_400_000
    return _to_dashboard_stats(await db.get_stats(since_ms))


@app.get("/api/stats")
async def get_stats() -> DashboardStats:
    return await fetch_stats()


class ThroughputBucket(BaseModel):
    ts: datetime
    succeeded: int
    errored: int
    running: int


# Range → (bucket unit, lookback ms). The unit is interpolated directly into
# adapter SQL via a closed mapping, so the set must stay closed to these
# literals.
_THROUGHPUT_RANGES: dict[str, tuple[Literal["hour", "day"], int]] = {
    "24h": ("hour", 24 * 3_600_000),
    "7d": ("day", 7 * 86_400_000),
    "30d": ("day", 30 * 86_400_000),
}


def _to_throughput_buckets(rows: list[ThroughputRow]) -> list[ThroughputBucket]:
    return [
        ThroughputBucket(
            ts=r.ts,
            succeeded=r.succeeded,
            errored=r.errored,
            running=r.running,
        )
        for r in rows
    ]


async def fetch_throughput(range_: Literal["24h", "7d", "30d"]) -> list[ThroughputBucket]:
    bucket, lookback_ms = _THROUGHPUT_RANGES[range_]
    until_ms = int(datetime.now(UTC).timestamp() * 1000)
    since_ms = until_ms - lookback_ms
    rows = await db.get_throughput(since_ms=since_ms, until_ms=until_ms, bucket=bucket)
    return _to_throughput_buckets(rows)


@app.get("/api/stats/timeseries")
async def get_throughput(
    range: Literal["24h", "7d", "30d"] = "7d",
) -> list[ThroughputBucket]:
    return await fetch_throughput(range)


class WorkflowSchedule(BaseModel):
    schedule_id: str
    schedule_name: str
    workflow_name: str
    workflow_class_name: str | None
    schedule: str
    status: str
    last_fired_at: str | None
    automatic_backfill: bool
    cron_timezone: str | None
    queue_name: str | None


def _to_workflow_schedule(r: ScheduleRow) -> WorkflowSchedule:
    return WorkflowSchedule(
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


async def fetch_schedules() -> list[WorkflowSchedule]:
    rows = await db.list_schedules()
    return [_to_workflow_schedule(r) for r in rows]


@app.get("/api/schedules")
async def list_schedules() -> list[WorkflowSchedule]:
    return await fetch_schedules()


class Queue(BaseModel):
    queue_id: str
    name: str
    concurrency: int | None
    worker_concurrency: int | None
    rate_limit_max: int | None
    rate_limit_period_sec: float | None
    priority_enabled: bool
    partition_queue: bool
    polling_interval_sec: float
    created_at_epoch_ms: int
    updated_at_epoch_ms: int
    enqueued: int
    running: int


def _to_queue(r: QueueRow) -> Queue:
    return Queue(
        queue_id=r.queue_id,
        name=r.name,
        concurrency=r.concurrency,
        worker_concurrency=r.worker_concurrency,
        rate_limit_max=r.rate_limit_max,
        rate_limit_period_sec=r.rate_limit_period_sec,
        priority_enabled=r.priority_enabled,
        partition_queue=r.partition_queue,
        polling_interval_sec=r.polling_interval_sec,
        created_at_epoch_ms=r.created_at_epoch_ms,
        updated_at_epoch_ms=r.updated_at_epoch_ms,
        enqueued=r.enqueued,
        running=r.running,
    )


async def fetch_queues() -> list[Queue]:
    rows = await db.list_queues()
    return [_to_queue(r) for r in rows]


@app.get("/api/queues")
async def list_queues() -> list[Queue]:
    return await fetch_queues()


class WorkflowAncestor(BaseModel):
    workflow_id: str
    name: str | None
    status: str | None


class NotificationItem(BaseModel):
    message_uuid: str
    destination_uuid: str
    topic: str | None
    consumed: bool
    created_at: datetime
    message: str | None
    serialization: str | None
    message_decoded: str | None
    # Chain from the topmost ancestor down to the destination workflow itself
    # (last entry). Empty when the destination row doesn't exist in
    # dbos.workflow_status.
    destination_ancestors: list[WorkflowAncestor]


def _to_notification_items(result: NotificationsRows) -> list[NotificationItem]:
    ancestors_by_seed: dict[str, list[WorkflowAncestor]] = {}
    for ar in result.ancestors:
        ancestors_by_seed.setdefault(ar.seed_id, []).append(
            WorkflowAncestor(workflow_id=ar.workflow_uuid, name=ar.name, status=ar.status)
        )
    return [
        NotificationItem(
            message_uuid=r.message_uuid,
            destination_uuid=r.destination_uuid,
            topic=r.topic,
            consumed=r.consumed,
            created_at=datetime.fromtimestamp(r.created_at_epoch_ms / 1000, tz=UTC),
            message=r.message,
            serialization=r.serialization,
            message_decoded=decode_dbos_value(r.message, r.serialization),
            destination_ancestors=ancestors_by_seed.get(r.destination_uuid, []),
        )
        for r in result.notifications
    ]


async def fetch_notifications(filters: NotificationFilters) -> list[NotificationItem]:
    result = await db.list_notifications(filters)
    return _to_notification_items(result)


@app.get("/api/notifications")
async def list_notifications(
    consumed: bool | None = None,
    destination_uuid: str | None = None,
    topic: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[NotificationItem]:
    return await fetch_notifications(
        NotificationFilters(
            limit=limit,
            consumed=consumed,
            destination_uuid=destination_uuid,
            topic=topic,
        )
    )


# Wire the WebSocket route before the SPA catch-all below — the catch-all
# `/{full_path:path}` would otherwise match `/ws` first.
_setup_realtime()


# Default to the SPA bundled inside the wheel at dbos_argus/_console/. Override
# with ARGUS_CONSOLE_DIR for dev (point at apps/console/build) or for the
# Docker image which copies the build to /app/console.
_BUNDLED_CONSOLE_DIR = Path(str(files("dbos_argus") / "_console"))
CONSOLE_DIR = Path(os.environ.get("ARGUS_CONSOLE_DIR") or _BUNDLED_CONSOLE_DIR)

if CONSOLE_DIR.is_dir() and (CONSOLE_DIR / "index.html").is_file():
    logger.info("serving console from %s", CONSOLE_DIR)

    @app.get("/{full_path:path}")
    async def console_spa(request: Request, full_path: str) -> FileResponse:
        candidate = (CONSOLE_DIR / full_path).resolve()
        try:
            candidate.relative_to(CONSOLE_DIR.resolve())
        except ValueError as e:
            raise HTTPException(status_code=404) from e
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(CONSOLE_DIR / "index.html")
else:
    logger.info("console static dir not found at %s; skipping SPA mount", CONSOLE_DIR)
