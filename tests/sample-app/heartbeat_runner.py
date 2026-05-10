"""Argus dev heartbeat runner — dequeues + executes scheduled heartbeat workflows.

The scheduler enqueues `heartbeat_check` rows onto `argus-heartbeats` every
minute (see `scheduled.register_schedules`). This process registers itself
as a worker for that queue and runs the workflow body. Stop it and the
heartbeat queue backs up; start it again and DBOS dequeues whatever's
pending.

Uses its own `executor_id` so cancelled/PENDING heartbeats it owns are
recovered only by another instance with the same id — not by the scheduler
or the runner.

Run:

    uv run argus-heartbeat-runner
"""

from __future__ import annotations

import logging
import os
import signal
import time

import click
from _dbos_setup import init_dbos
from dbos import DBOS, Queue

LOG = logging.getLogger("heartbeat-runner")

EXECUTOR_ID = "heartbeat-runner"

init_dbos(EXECUTOR_ID, worker_queue=None)

# Decorator in `scheduled` registers `heartbeat_check` against the DBOS
# singleton constructed above — this import must come AFTER `DBOS(...)`.
import scheduled  # noqa: E402

# Subscribe this process as a worker for the heartbeats queue.
Queue(scheduled.HEARTBEAT_QUEUE_NAME, worker_concurrency=50)


@click.command()
def main() -> None:
    """Launch DBOS and idle while the queue worker drains heartbeats."""
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    LOG.info(
        "heartbeat-runner up — executor_id=%s, queue=%s",
        EXECUTOR_ID,
        scheduled.HEARTBEAT_QUEUE_NAME,
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
