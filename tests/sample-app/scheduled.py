"""Scheduled workflows for the Argus dev fixture.

`argus-scheduler` imports this module to own the cron tick loop and the
`workflow_schedules` row. The schedule is registered with a `queue_name`,
so each tick enqueues a `heartbeat_check` row onto `argus-heartbeats`
rather than running it locally — execution is picked up by whichever
process registers itself as a worker for that queue (`argus-heartbeat-runner`).

Uses the modern `DBOS.create_schedule(...)` API. The decorator-based
`@DBOS.scheduled(...)` form is deprecated upstream and doesn't persist to
`dbos.workflow_schedules`.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any

from dbos import DBOS
from workflows import audit, log_event

HEARTBEAT_SCHEDULE_NAME = "argus-demo-heartbeat"
HEARTBEAT_SCHEDULE = "* * * * *"
HEARTBEAT_QUEUE_NAME = "argus-heartbeats"

HEARTBEAT_JITTER_MIN_SEC = 0
HEARTBEAT_JITTER_MAX_SEC = 2


@DBOS.step()
def random_jitter() -> int:
    """Sleep a random 1–30s so heartbeat runs have varied durations.

    Runs as a step (not a plain function) so the chosen delay is recorded as a
    step output — useful when the dashboard later charts per-run durations.
    """
    seconds = random.randint(HEARTBEAT_JITTER_MIN_SEC, HEARTBEAT_JITTER_MAX_SEC)
    time.sleep(seconds)
    return seconds


@DBOS.workflow()
def heartbeat_check(scheduled_at: datetime, context: Any = None) -> None:
    """Tick every minute. Each run lands a workflow row in the dashboard.

    `DBOS.create_schedule` invokes `(scheduled_at, context)` — `context` is
    whatever was passed to `create_schedule(context=...)`, defaulting to None.
    (Note: the deprecated `@DBOS.scheduled` decorator passed `(scheduled_at,
    actual_at)` instead — different second argument.)
    """
    audit(f"heartbeat:{scheduled_at.isoformat()}")
    waited = random_jitter()
    log_event(f"heartbeat ran (scheduled for {scheduled_at.isoformat()}, jitter={waited}s)")


def register_schedules() -> None:
    """Idempotent — register the heartbeat schedule at the configured cadence.

    Routes through `HEARTBEAT_QUEUE_NAME` so ticks enqueue rather than run
    on the scheduler. If the persisted schedule row predates the queue
    (cadence matches but `queue_name` is unset/different), it's recreated.
    """
    existing = DBOS.list_schedules(schedule_name_prefix=HEARTBEAT_SCHEDULE_NAME)
    for schedule in existing:
        if schedule["schedule_name"] != HEARTBEAT_SCHEDULE_NAME:
            continue
        if (
            schedule["schedule"] == HEARTBEAT_SCHEDULE
            and schedule.get("queue_name") == HEARTBEAT_QUEUE_NAME
        ):
            return
        DBOS.delete_schedule(HEARTBEAT_SCHEDULE_NAME)
        break
    DBOS.create_schedule(
        schedule_name=HEARTBEAT_SCHEDULE_NAME,
        workflow_fn=heartbeat_check,
        schedule=HEARTBEAT_SCHEDULE,
        queue_name=HEARTBEAT_QUEUE_NAME,
    )
