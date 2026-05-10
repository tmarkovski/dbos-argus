"""Argus dev scheduler — long-running process that owns the cron schedule.

Sets `executor_id="scheduler"` so the heartbeat workflow runs under its
own identity, separate from `argus-runner` (demo workflows) and `argus-ops`
(short-lived CLI). That way you can stop the runner — or run another sample
variant — without the heartbeat tagging along, and DBOS recovery only resumes
PENDING heartbeats on this executor.

Run:

    uv run argus-scheduler

The schedule row in `dbos.workflow_schedules` is persisted across restarts;
this process just owns the in-memory tick loop. Stop the process and ticks
stop; start it again and they resume.
"""

from __future__ import annotations

import logging
import os
import signal
import time

import click
from _dbos_setup import init_dbos
from dbos import DBOS, Queue

LOG = logging.getLogger("scheduler")

EXECUTOR_ID = "scheduler"

init_dbos(EXECUTOR_ID, worker_queue=None)

import scheduled  # noqa: E402  — defines `heartbeat_check` workflow + register_schedules()

# Declare the heartbeats queue so `create_schedule(..., queue_name=...)` accepts
# it, but with `worker_concurrency=0` so this process never dequeues. Heartbeat
# execution belongs to `argus-heartbeat-runner`.
Queue(scheduled.HEARTBEAT_QUEUE_NAME, worker_concurrency=0)


@click.command()
def main() -> None:
    """Launch DBOS, register the heartbeat schedule, and idle."""
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    scheduled.register_schedules()
    LOG.info(
        "scheduler up — executor_id=%s, schedule=%s @ %s",
        EXECUTOR_ID,
        scheduled.HEARTBEAT_SCHEDULE_NAME,
        scheduled.HEARTBEAT_SCHEDULE,
    )

    stop = {"now": False, "count": 0}

    # Second SIGINT escalates to a hard exit — DBOS.destroy() waits for any
    # in-flight workflows to drain (notably DBOS.sleep, which is not
    # interruptible) and can otherwise hold the process indefinitely.
    def _on_signal(_signum, _frame):
        stop["count"] += 1
        if stop["count"] >= 2:
            LOG.warning("force exit (second ctrl-C)")
            os._exit(130)
        stop["now"] = True
        LOG.info("shutdown requested — ctrl-C again to force exit")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    while not stop["now"]:
        time.sleep(1)
    LOG.info("shutting down")
    DBOS.destroy()


if __name__ == "__main__":
    main()
