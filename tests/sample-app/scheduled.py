"""Scheduled workflows for the Argus dev fixture.

Imported only by the runner — `create_schedule(...)` is a one-time DB write
(idempotent here via a list-then-create check), and the runner is the
worker that should host the schedule's executions.

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

HEARTBEAT_JITTER_MIN_SEC = 1
HEARTBEAT_JITTER_MAX_SEC = 30


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
    """Idempotent — register the heartbeat schedule at the configured cadence."""
    existing = DBOS.list_schedules(schedule_name_prefix=HEARTBEAT_SCHEDULE_NAME)
    for schedule in existing:
        if schedule["schedule_name"] != HEARTBEAT_SCHEDULE_NAME:
            continue
        if schedule["schedule"] == HEARTBEAT_SCHEDULE:
            return
        DBOS.delete_schedule(HEARTBEAT_SCHEDULE_NAME)
        break
    DBOS.create_schedule(
        schedule_name=HEARTBEAT_SCHEDULE_NAME,
        workflow_fn=heartbeat_check,
        schedule=HEARTBEAT_SCHEDULE,
    )
