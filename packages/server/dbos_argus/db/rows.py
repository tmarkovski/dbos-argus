"""Typed row & filter shapes that the `ArgusDB` adapter exposes.

Adapters return these dataclasses; `main.py` maps them to the public Pydantic
response models. They mirror the columns each endpoint actually needs — the
`*_ms` integers are unix epoch milliseconds (DBOS' native time unit), so
adapters can stay dialect-neutral about timestamp conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WorkflowFilters:
    limit: int = 50
    q: str | None = None
    started_after_ms: int | None = None
    started_before_ms: int | None = None
    statuses: list[str] | None = None
    queue_name: str | None = None
    hide_scheduled: bool = False
    grouped: bool = True


@dataclass(frozen=True)
class NotificationFilters:
    limit: int = 200
    consumed: bool | None = None
    destination_uuid: str | None = None
    topic: str | None = None


@dataclass(frozen=True)
class WorkflowListRow:
    workflow_uuid: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    queue_name: str | None
    executor_id: str | None
    priority: int | None
    started_ms: int
    updated_ms: int
    # Wall-clock completion time (workflow_status.completed_at). None while the
    # workflow is still running/enqueued, or null on rows DBOS wrote before it
    # stamped completions.
    completed_ms: int | None
    depth: int
    op_count: int


@dataclass(frozen=True)
class WorkflowFamilyRow:
    workflow_uuid: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    queue_name: str | None
    executor_id: str | None
    schedule_name: str | None
    attributes: object | None
    recovery_attempts: int | None
    workflow_timeout_ms: int | None
    has_output: bool
    has_error: bool
    started_ms: int
    updated_ms: int
    # Wall-clock completion time (workflow_status.completed_at); None until the
    # workflow reaches a terminal state.
    completed_ms: int | None
    depth: int


@dataclass(frozen=True)
class StepRow:
    workflow_uuid: str
    function_id: int
    function_name: str | None
    has_output: bool
    has_error: bool
    child_workflow_id: str | None
    started_at_epoch_ms: int | None
    completed_at_epoch_ms: int | None
    event_key: str | None
    # Raw `output` for `DBOS.sleep` rows — main.py turns it into the
    # originally-requested duration. Always None for non-sleep rows.
    sleep_output_raw: str | None


@dataclass(frozen=True)
class EventRow:
    workflow_uuid: str
    key: str
    current_value: str
    current_serialization: str | None
    function_id: int | None
    history_value: str | None
    history_serialization: str | None
    completed_at_epoch_ms: int | None


@dataclass(frozen=True)
class WorkflowDetailRows:
    family: list[WorkflowFamilyRow]
    steps: list[StepRow]
    events: list[EventRow]


@dataclass(frozen=True)
class ResultRow:
    output: str | None
    error: str | None
    serialization: str | None


@dataclass(frozen=True)
class StatsRow:
    total: int
    in_flight: int
    enqueued: int
    failed_recent: int
    pending_notifications: int
    active_schedules: int
    total_queues: int


@dataclass(frozen=True)
class ThroughputRow:
    ts: datetime
    succeeded: int
    errored: int
    running: int


@dataclass(frozen=True)
class ScheduleRow:
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


@dataclass(frozen=True)
class QueueRow:
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
    # Live counts joined from workflow_status — workflows currently sitting in
    # this queue waiting for a worker (ENQUEUED) and ones a worker has picked
    # up but hasn't finished (PENDING). The link is by name (workflow_status
    # carries no FK to queues), so a count can refer to a queue_name that
    # doesn't appear in `dbos.queues` if no worker has registered it; those
    # rows are dropped by the inner join in the SQL.
    enqueued: int
    running: int


@dataclass(frozen=True)
class NotificationRow:
    message_uuid: str
    destination_uuid: str
    topic: str | None
    consumed: bool
    created_at_epoch_ms: int
    message: str | None
    serialization: str | None


@dataclass(frozen=True)
class AncestorRow:
    seed_id: str
    workflow_uuid: str
    name: str | None
    status: str | None
    lvl: int


@dataclass(frozen=True)
class NotificationsRows:
    notifications: list[NotificationRow]
    ancestors: list[AncestorRow]


def normalize_json_value(value: object | None) -> object | None:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
