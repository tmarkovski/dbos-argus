"""Minimal DBOS Transact app that connects to Argus.

This file is a scaffold. It imports `dbos`, declares a single durable workflow,
and attempts to open a WebSocket to Argus at ws://localhost:8090/ws/apps.
End-to-end integration (auth, event forwarding, intervention) is not wired up.

Run manually:

    cd examples/python-hello-workflow
    uv sync
    uv run python main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

try:
    from dbos import DBOS
except ImportError as e:  # pragma: no cover - surfaces only when `dbos` isn't installed
    raise SystemExit(
        "The 'dbos' package is required. Install with `uv sync` in this example directory."
    ) from e

LOG = logging.getLogger("argus-example")
ARGUS_URL = os.environ.get("ARGUS_URL", "ws://localhost:8090/ws/apps")
ARGUS_API_KEY = os.environ.get("ARGUS_API_KEY", "local-dev-key")

DBOS_SYSTEM_DB = os.environ.get(
    "DBOS_SYSTEM_DATABASE_URL", "postgresql://argus:argus@localhost:5432/argus"
)
DBOS(config={"name": "hello-workflow", "system_database_url": DBOS_SYSTEM_DB})


@DBOS.workflow()
def hello_workflow(name: str) -> str:
    return f"hello, {name}"


@DBOS.workflow()
def greet_child(name: str, nested: bool = False) -> str:
    if nested:
        inner = DBOS.start_workflow(greet_child, name, nested=False)
        return f"(child) hi, {name} | inner={inner.get_result()}"
    return f"(child) hi, {name}"


@DBOS.workflow()
def greet_parent(name: str) -> str:
    branch = DBOS.start_workflow(greet_child, name, nested=True)
    leaf = DBOS.start_workflow(greet_child, name, nested=False)
    return f"(parent) got: [{branch.get_result()}] and [{leaf.get_result()}]"


async def connect_to_argus() -> None:
    try:
        import websockets
    except ImportError:
        LOG.warning("`websockets` not installed — skipping Argus connection demo.")
        return

    async with websockets.connect(f"{ARGUS_URL}?api_key={ARGUS_API_KEY}") as ws:
        hello = await ws.recv()
        LOG.info("Argus greeted us: %s", hello)
        await ws.send(
            json.dumps(
                {
                    "type": "app.connect",
                    "app_name": "hello-workflow",
                    "sdk": "python",
                    "sdk_version": "0.0.1",
                }
            )
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    LOG.info("hello_workflow result: %s", hello_workflow("argus"))
    LOG.info("greet_parent result: %s", greet_parent("argus"))
    asyncio.run(connect_to_argus())


if __name__ == "__main__":
    main()
