"""Argus dev ops — short-lived CLI for poking at workflows the simulator runs.

Runs under `executor_id="ops"`. Cross-executor send / cancel / resume work
fine — they're plain DB ops.

Run:

    argus-ops --help
    argus-ops list --status PENDING
    argus-ops send <wf-id> --topic email-verify --message '{"clicked": true}'
    argus-ops cancel <wf-id>
"""

from __future__ import annotations

import json
import logging
from typing import Any

import click
from _dbos_setup import init_dbos
from dbos import DBOS

LOG = logging.getLogger("ops")

EXECUTOR_ID = "ops"

init_dbos(EXECUTOR_ID, worker_queue=None)

import workflows  # noqa: E402, F401  — register workflow decorators


@click.group()
def cli() -> None:
    """Inspect, signal, cancel, and resume workflows the simulator started."""
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
    help="Filter by executor_id (e.g. orders-worker).",
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


if __name__ == "__main__":
    cli()
