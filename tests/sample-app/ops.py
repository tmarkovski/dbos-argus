"""Argus dev ops — short-lived CLI for poking at workflows the runner spawned.

Runs under `executor_id="argus-ops"` so DBOS recovery never picks up the
runner's PENDING workflows here. Cross-executor send / cancel / resume work
fine — they're plain DB ops.

Run:

    uv run argus-ops --help
    uv run argus-ops list --status PENDING
    uv run argus-ops carrier-confirm fulfill-ab12cd34
    uv run argus-ops send <wf-id> --topic my-topic --message '{"k":"v"}'
"""

from __future__ import annotations

import json
import logging
from typing import Any

import click
from _dbos_setup import init_dbos
from dbos import DBOS

LOG = logging.getLogger("argus-ops")

EXECUTOR_ID = "argus-ops"
CARRIER_CONFIRMATION_TOPIC = "carrier-confirmation"
OPS_SIGNOFF_TOPIC = "ops-signoff"

# `is_worker=False` registers the demo queue with worker_concurrency=0, so this
# process can enqueue but never dequeues — the runner does the work.
init_dbos(EXECUTOR_ID, is_worker=False)

# Decorators in `workflows` register against the DBOS singleton constructed
# above — must come AFTER `init_dbos`. Imported here so `enqueue` can pass
# function references to `Queue.enqueue(...)`.
import _dbos_setup  # noqa: E402
from workflows import (  # noqa: E402
    fulfill_order,
    process_order,
    send_campaign,
)


@click.group()
def cli() -> None:
    """Dev tools for posting messages, cancelling, and inspecting workflows."""
    logging.basicConfig(level=logging.WARNING)
    DBOS.launch()


@cli.command()
@click.argument("workflow_id")
@click.option("--topic", default=None, help="Topic name (omit for default channel).")
@click.option(
    "--message",
    "message_json",
    default="null",
    show_default=True,
    help="JSON-encoded payload.",
)
def send(workflow_id: str, topic: str | None, message_json: str) -> None:
    """Send a notification to a workflow's DBOS.recv."""
    payload: Any = json.loads(message_json)
    DBOS.send(workflow_id, payload, topic=topic)
    click.echo(f"sent → {workflow_id} (topic={topic!r}): {payload!r}")


@cli.command()
@click.argument("workflow_id")
def cancel(workflow_id: str) -> None:
    """Cancel a workflow by id."""
    DBOS.cancel_workflow(workflow_id)
    click.echo(f"cancelled → {workflow_id}")


@cli.command()
@click.argument("workflow_id")
def resume(workflow_id: str) -> None:
    """Resume a cancelled or pending workflow by id."""
    DBOS.resume_workflow(workflow_id)
    click.echo(f"resumed → {workflow_id}")


@cli.command("list")
@click.option("--limit", default=20, type=int, show_default=True)
@click.option("--status", default=None, help="Filter by status (PENDING, SUCCESS, …).")
@click.option(
    "--executor",
    default=None,
    help="Filter by executor_id (e.g. argus-runner).",
)
def list_workflows(limit: int, status: str | None, executor: str | None) -> None:
    """List recent workflows in the system DB."""
    rows = DBOS.list_workflows(
        limit=limit,
        status=status,
        executor_id=executor,
        sort_desc=True,
        load_input=False,
        load_output=False,
    )
    if not rows:
        click.echo("(no workflows)")
        return
    for row in rows:
        click.echo(f"{row.status:<12} {row.workflow_id:<48} [{row.executor_id or '-'}] {row.name}")


@cli.command("carrier-confirm")
@click.argument("fulfill_workflow_id")
def carrier_confirm(fulfill_workflow_id: str) -> None:
    """Send the canonical carrier confirmation to a fulfill_order's dispatch_carrier child."""
    target = f"{fulfill_workflow_id}-carrier"
    payload = {"confirmed_by": "ops", "tracking_no": "TRK-99001"}
    DBOS.send(target, payload, topic=CARRIER_CONFIRMATION_TOPIC)
    click.echo(f"carrier-confirm → {target}: {payload!r}")


@cli.command("ops-signoff")
@click.argument("fulfill_workflow_id")
def ops_signoff(fulfill_workflow_id: str) -> None:
    """Send the trailing ops-signoff so fulfill_order can complete."""
    payload = {"approved_by": "ops"}
    DBOS.send(fulfill_workflow_id, payload, topic=OPS_SIGNOFF_TOPIC)
    click.echo(f"ops-signoff → {fulfill_workflow_id}: {payload!r}")


@cli.command("cancel-stock")
@click.argument("fulfill_workflow_id")
def cancel_stock(fulfill_workflow_id: str) -> None:
    """Cancel the stock_check grandchild under a fulfill_order tree."""
    target = f"{fulfill_workflow_id}-reconcile-stock"
    DBOS.cancel_workflow(target)
    click.echo(f"cancelled → {target}")


@cli.group()
def enqueue() -> None:
    """Enqueue a workflow onto the demo queue. The runner picks it up."""


@enqueue.command("order")
@click.argument("order_id")
def enqueue_order(order_id: str) -> None:
    """Enqueue process_order(order_id)."""
    handle = _dbos_setup.DEMO_QUEUE.enqueue(process_order, order_id)
    click.echo(f"enqueued process_order → {handle.workflow_id}")


@enqueue.command("campaign")
@click.argument("campaign_id")
@click.option("-n", "--count", default=5, type=int, show_default=True)
def enqueue_campaign(campaign_id: str, count: int) -> None:
    """Enqueue send_campaign(campaign_id, count)."""
    handle = _dbos_setup.DEMO_QUEUE.enqueue(send_campaign, campaign_id, count)
    click.echo(f"enqueued send_campaign → {handle.workflow_id}")


@enqueue.command("fulfill")
@click.argument("order_id")
def enqueue_fulfill(order_id: str) -> None:
    """Enqueue fulfill_order(order_id) (will block on its trailing recv until ops-signoff)."""
    handle = _dbos_setup.DEMO_QUEUE.enqueue(fulfill_order, order_id)
    click.echo(f"enqueued fulfill_order → {handle.workflow_id}")


if __name__ == "__main__":
    cli()
