"""Argus dev runner — short-lived queue worker.

Spawned by `argus-simulator` to drain a single queue for a fixed duration, then
exit. All instances of a worker for the same queue share an executor_id (e.g.
`orders-worker`) so DBOS recovery can pick up a predecessor's PENDING
work on the next spawn.

Run:

    argus-runner --queue orders --duration 60
    argus-runner idle                       # launch DBOS, register workflows, idle (recovery only)
"""

from __future__ import annotations

import logging
import os
import signal
import time

import click
from _dbos_setup import QUEUE_CONFIGS, init_dbos
from dbos import DBOS

LOG = logging.getLogger("runner")


def _executor_id_for(queue: str) -> str:
    return f"{queue}-worker"


@click.group(invoke_without_command=True)
@click.option(
    "--queue",
    "queue",
    type=click.Choice(sorted(QUEUE_CONFIGS), case_sensitive=False),
    default=None,
    help="Subscribe as a worker for this queue and drain for --duration seconds.",
)
@click.option(
    "--duration",
    type=int,
    default=60,
    show_default=True,
    help="How many seconds to drain the queue before exiting (with --queue).",
)
@click.pass_context
def main(ctx: click.Context, queue: str | None, duration: int) -> None:
    """Drain a queue for N seconds and exit. With no flags, defaults to `idle`."""
    logging.basicConfig(level=logging.INFO)
    if ctx.invoked_subcommand is not None:
        return
    if queue is None:
        ctx.invoke(idle)
        return
    _drain(queue, duration)


@main.command()
def idle() -> None:
    """Launch DBOS without subscribing to any queue. Useful for recovery testing."""
    init_dbos("runner-idle", worker_queue=None)
    import workflows  # noqa: F401  — register workflow decorators

    DBOS.launch()
    LOG.info("runner idle — no queues subscribed")
    _idle_loop()


def _drain(queue: str, duration: int) -> None:
    executor_id = _executor_id_for(queue)
    init_dbos(executor_id, worker_queue=queue)

    import workflows  # noqa: F401  — register workflow decorators

    DBOS.launch()
    LOG.info(
        "draining queue=%s as executor_id=%s for %ds (concurrency=%d)",
        queue,
        executor_id,
        duration,
        QUEUE_CONFIGS[queue],
    )

    stop = {"now": False, "count": 0}

    def _on_signal(_signum, _frame):
        stop["count"] += 1
        if stop["count"] >= 2:
            LOG.warning("force exit (second signal)")
            os._exit(130)
        stop["now"] = True
        LOG.info("shutdown requested — second signal forces exit")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    deadline = time.monotonic() + duration
    while not stop["now"] and time.monotonic() < deadline:
        time.sleep(0.5)

    LOG.info("worker draining complete — destroying DBOS")
    DBOS.destroy()


def _idle_loop() -> None:
    stop = {"now": False, "count": 0}

    def _on_signal(_signum, _frame):
        stop["count"] += 1
        if stop["count"] >= 2:
            LOG.warning("force exit (second signal)")
            os._exit(130)
        stop["now"] = True
        LOG.info("shutdown requested — second signal forces exit")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    while not stop["now"]:
        time.sleep(1)
    LOG.info("shutting down")
    DBOS.destroy()


if __name__ == "__main__":
    main()
