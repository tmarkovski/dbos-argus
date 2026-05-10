"""Argus dev metrics runner — dequeues + executes scheduled platform-ops workflows.

The scheduler enqueues rows from `scheduled.SCHEDULES` (metrics rollup, cart
sweep, inventory reconcile) onto the `metrics` queue every 5–15 minutes (see
`scheduled.register_schedules`). This process registers itself as a worker
for that queue and runs the workflow bodies. Stop it and the queue backs up;
start it again and DBOS dequeues whatever's pending.

Uses its own `executor_id` so cancelled/PENDING workflows it owns are
recovered only by another instance with the same id — not by the scheduler
or the per-use-case runners.

Run:

    uv run argus-metrics-runner
"""

from __future__ import annotations

import logging
import os
import signal
import time

import click
from _dbos_setup import init_dbos, register_queues
from dbos import DBOS

LOG = logging.getLogger("metrics-runner")

EXECUTOR_ID = "metrics-runner"

init_dbos(EXECUTOR_ID, worker_queue="metrics")

# Decorator in `scheduled` registers the scheduled workflows against the DBOS
# singleton constructed above — this import must come AFTER `DBOS(...)`.
import scheduled  # noqa: E402


@click.command()
def main() -> None:
    """Launch DBOS and idle while the queue worker drains scheduled workflows."""
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    register_queues()
    LOG.info(
        "metrics-runner up — executor_id=%s, queue=%s",
        EXECUTOR_ID,
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
