"""Argus dev runner — long-running process that hosts the example workflows.

Sets `executor_id="argus-runner"` so it owns the workflows it starts. The
sibling `argus-ops` (short-lived CLI) and `argus-scheduler` (cron heartbeat)
processes use distinct executor IDs and share the Postgres; DBOS recovery
filters by executor_id, so none of them pick up each other's PENDING work.

Run:

    cd tests/sample-app
    uv sync
    uv run argus-runner            # seeds the demo tree and idles
    uv run argus-runner start-order ord-2002
    uv run argus-runner --help
"""

from __future__ import annotations

import logging
import os
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
from workflows import (  # noqa: E402
    fulfill_order,
    process_order,
    send_campaign,
)


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
    DBOS.launch()
    LOG.info("argus-runner up — executor_id=%s", EXECUTOR_ID)

    # Fire-and-forget so all three trees run concurrently — with the random
    # 3-10s step pauses, awaiting `process_order` / `send_campaign` here would
    # delay `fulfill_order`'s start by minutes.
    process_handle = DBOS.start_workflow(process_order, "ord-1001")
    campaign_handle = DBOS.start_workflow(send_campaign, "spring-sale", 20)
    LOG.info("started process_order: %s", process_handle.workflow_id)
    LOG.info("started send_campaign: %s", campaign_handle.workflow_id)

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
    DBOS.launch()
    LOG.info("process_order result: %s", process_order(order_id))
    _idle()


@main.command("start-campaign")
@click.argument("campaign_id")
@click.option("-n", "--count", default=5, type=int, show_default=True)
def start_campaign(campaign_id: str, count: int) -> None:
    """Run a single send_campaign workflow synchronously, then idle."""
    DBOS.launch()
    LOG.info("send_campaign result: %s", send_campaign(campaign_id, count))
    _idle()


@main.command("start-fulfill")
@click.argument("order_id")
def start_fulfill(order_id: str) -> None:
    """Spawn fulfill_order(order_id) fire-and-forget, print its id, then idle."""
    DBOS.launch()
    fulfill_workflow_id = f"fulfill-{uuid.uuid4().hex[:8]}"
    with SetWorkflowID(fulfill_workflow_id):
        DBOS.start_workflow(fulfill_order, order_id)
    LOG.info("started fulfill_order: %s", fulfill_workflow_id)
    _idle()


@main.command()
def idle() -> None:
    """Launch DBOS and idle — useful to recover prior runner workflows."""
    DBOS.launch()
    LOG.info("argus-runner up — executor_id=%s (no new workflows seeded)", EXECUTOR_ID)
    _idle()


def _idle() -> None:
    LOG.info("idle — workflows owned by executor_id=%s; ctrl-C to exit", EXECUTOR_ID)
    stop = {"now": False, "count": 0}

    # First SIGINT requests graceful shutdown. `DBOS.destroy()` waits for
    # in-flight workflow threads to drain — a workflow mid-`DBOS.sleep(N)`
    # holds the process for up to N seconds because DBOS.sleep is not
    # interruptible. A second SIGINT escalates to a hard exit so the user
    # is never stuck staring at "shutting down".
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
