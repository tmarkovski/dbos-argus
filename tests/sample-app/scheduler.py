"""Argus dev scheduler — long-running process that owns the cron schedules.

Sets `executor_id="scheduler"` so the schedule tick rows run under their own
identity, separate from `argus-runner` (use-case workflows) and `argus-ops`
(short-lived CLI). That way you can stop the runner — or run another sample
variant — without the scheduled workflows tagging along, and DBOS recovery
only resumes PENDING ticks on this executor.

Run:

    uv run argus-scheduler

Schedule rows in `dbos.workflow_schedules` are persisted across restarts;
this process just owns the in-memory tick loop. Stop the process and ticks
stop; start it again and they resume.
"""

from __future__ import annotations

import logging
import os
import signal
import time

import click
from _dbos_setup import init_dbos, register_queues
from dbos import DBOS

LOG = logging.getLogger("scheduler")

EXECUTOR_ID = "scheduler"

init_dbos(EXECUTOR_ID, worker_queue=None)

import scheduled  # noqa: E402  — defines the scheduled workflows + register_schedules()


@click.command()
def main() -> None:
    """Launch DBOS, register the cron schedules, and idle."""
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    register_queues()
    scheduled.register_schedules()
    LOG.info(
        "scheduler up — executor_id=%s, schedules=%s, queue=%s",
        EXECUTOR_ID,
        [s[0] for s in scheduled.SCHEDULES],
        scheduled.METRICS_QUEUE_NAME,
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
    DBOS.destroy(workflow_completion_timeout_sec=15)


if __name__ == "__main__":
    main()
