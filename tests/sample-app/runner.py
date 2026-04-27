"""Argus dev runner — long-running process that hosts the example workflows.

Sets `executor_id="argus-runner"` so it owns the workflows it starts. A
separate `argus-ops` process (different executor_id) handles the manual
side-effects: sending notifications, cancelling, etc. They share the Postgres
but DBOS recovery filters by executor_id, so they don't pick up each other's
PENDING workflows.

Run:

    cd tests/sample-app
    uv sync
    uv run argus-runner            # seeds the demo tree and idles
    uv run argus-runner start-order ord-2002
    uv run argus-runner --help
"""

from __future__ import annotations

import logging
import signal
import time
import uuid

import click
from _dbos_setup import init_dbos
from dbos import DBOS, SetWorkflowID

LOG = logging.getLogger("argus-runner")

EXECUTOR_ID = "argus-runner"

init_dbos(EXECUTOR_ID)

# Decorators in `workflows` register against the DBOS singleton constructed
# above — so this import must come AFTER `DBOS(...)`.
import scheduled  # noqa: E402  — defines `heartbeat_check` workflow + register_schedules()
from workflows import (  # noqa: E402
    fulfill_order,
    process_order,
    send_campaign,
)


def _launch() -> None:
    """DBOS.launch + idempotent schedule registration."""
    DBOS.launch()
    scheduled.register_schedules()


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Run example workflows under executor_id='argus-runner' and idle."""
    logging.basicConfig(level=logging.INFO)
    if ctx.invoked_subcommand is None:
        ctx.invoke(seed)


@main.command()
def seed() -> None:
    """Spawn the full demo workflow tree, then idle until ctrl-C."""
    _launch()
    LOG.info("argus-runner up — executor_id=%s", EXECUTOR_ID)

    LOG.info("process_order result: %s", process_order("ord-1001"))
    LOG.info("send_campaign result: %s", send_campaign("spring-sale", 20))

    fulfill_workflow_id = f"fulfill-{uuid.uuid4().hex[:8]}"
    with SetWorkflowID(fulfill_workflow_id):
        DBOS.start_workflow(fulfill_order, "ord-1001")
    LOG.info("started fulfill_order: %s", fulfill_workflow_id)
    LOG.info("  carrier child:    %s-carrier", fulfill_workflow_id)
    LOG.info("  reconcile child:  %s-reconcile", fulfill_workflow_id)
    LOG.info("  stock grandchild: %s-reconcile-stock", fulfill_workflow_id)
    LOG.info("Run from another shell:")
    LOG.info("  uv run argus-ops carrier-confirm %s", fulfill_workflow_id)
    LOG.info("  uv run argus-ops cancel-stock    %s", fulfill_workflow_id)
    LOG.info("  uv run argus-ops ops-signoff     %s", fulfill_workflow_id)

    _idle()


@main.command("start-order")
@click.argument("order_id")
def start_order(order_id: str) -> None:
    """Run a single process_order workflow synchronously, then idle."""
    _launch()
    LOG.info("process_order result: %s", process_order(order_id))
    _idle()


@main.command("start-campaign")
@click.argument("campaign_id")
@click.option("-n", "--count", default=5, type=int, show_default=True)
def start_campaign(campaign_id: str, count: int) -> None:
    """Run a single send_campaign workflow synchronously, then idle."""
    _launch()
    LOG.info("send_campaign result: %s", send_campaign(campaign_id, count))
    _idle()


@main.command("start-fulfill")
@click.argument("order_id")
def start_fulfill(order_id: str) -> None:
    """Spawn fulfill_order(order_id) fire-and-forget, print its id, then idle."""
    _launch()
    fulfill_workflow_id = f"fulfill-{uuid.uuid4().hex[:8]}"
    with SetWorkflowID(fulfill_workflow_id):
        DBOS.start_workflow(fulfill_order, order_id)
    LOG.info("started fulfill_order: %s", fulfill_workflow_id)
    _idle()


@main.command()
def idle() -> None:
    """Launch DBOS and idle — useful to recover prior runner workflows."""
    _launch()
    LOG.info("argus-runner up — executor_id=%s (no new workflows seeded)", EXECUTOR_ID)
    _idle()


def _idle() -> None:
    LOG.info("idle — workflows owned by executor_id=%s; ctrl-C to exit", EXECUTOR_ID)
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
