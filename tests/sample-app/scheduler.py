"""Argus dev scheduler — long-running process that owns the cron schedule.

Sets `executor_id="argus-scheduler"` so the heartbeat workflow runs under its
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
import signal
import time

import click
from _dbos_setup import init_dbos
from dbos import DBOS

LOG = logging.getLogger("argus-scheduler")

EXECUTOR_ID = "argus-scheduler"

init_dbos(EXECUTOR_ID)

import scheduled  # noqa: E402  — defines `heartbeat_check` workflow + register_schedules()


@click.command()
def main() -> None:
    """Launch DBOS, register the heartbeat schedule, and idle."""
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    scheduled.register_schedules()
    LOG.info(
        "argus-scheduler up — executor_id=%s, schedule=%s @ %s",
        EXECUTOR_ID,
        scheduled.HEARTBEAT_SCHEDULE_NAME,
        scheduled.HEARTBEAT_SCHEDULE,
    )

    stop = {"now": False}

    def _on_signal(_signum, _frame):
        stop["now"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    while not stop["now"]:
        time.sleep(1)
    LOG.info("shutting down")
    DBOS.destroy()


if __name__ == "__main__":
    main()
