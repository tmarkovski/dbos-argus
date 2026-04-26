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
import time

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


@DBOS.step()
def fetch_template(name: str) -> dict:
    time.sleep(0.08)
    return {"template": f"hello, {name}", "source": "static"}


@DBOS.step()
def translate(message: str, locale: str) -> dict:
    time.sleep(0.04)
    suffix = {"es": "¡hola!", "fr": "bonjour!", "jp": "こんにちは!"}.get(locale, "")
    return {
        "locale": locale,
        "original": message,
        "translated": f"{message} {suffix}".strip(),
    }


@DBOS.step()
def log_greeting(message: str) -> None:
    time.sleep(0.02)
    LOG.info("greeting: %s", message)


@DBOS.step()
def audit(action: str) -> dict:
    time.sleep(0.01)
    return {"action": action, "actor": "hello-workflow"}


@DBOS.step()
def shout(text: str) -> str:
    time.sleep(0.01)
    return text.upper() + "!"


@DBOS.step()
def count_chars(text: str) -> int:
    time.sleep(0.01)
    return len(text)


@DBOS.step()
def flaky_check(name: str) -> None:
    time.sleep(0.02)
    raise ValueError(f"simulated transient failure for {name!r}")


@DBOS.workflow()
def risky_child(name: str) -> dict:
    # Always blows up inside a step, so both the step and this workflow
    # land in ERROR state — gives the UI a failing branch to display.
    flaky_check(name)
    return {"name": name, "ok": True}


@DBOS.workflow()
def hello_workflow(name: str) -> dict:
    template = fetch_template(name)
    translation = translate(template["template"], "es")
    loud = shout(translation["translated"])
    size = count_chars(loud)
    log_greeting(translation["translated"])
    audit(f"hello:{name}")
    return {
        "name": name,
        "greeting": translation["translated"],
        "shouted": loud,
        "char_count": size,
        "locale": translation["locale"],
    }


@DBOS.workflow()
def loop_workflow(name: str) -> dict:
    greetings = [shout(f"{name}-{i}") for i in range(5)]
    return {"name": name, "greetings": greetings}


@DBOS.workflow()
def greet_child(name: str, nested: bool = False) -> dict:
    template = fetch_template(name)
    if nested:
        inner = DBOS.start_workflow(greet_child, name, nested=False)
        inner.get_result()  # wait for the child without folding it into our output
    log_greeting(template["template"])
    return {
        "kind": "child",
        "name": name,
        "greeting": template["template"],
        "nested": nested,
    }


@DBOS.workflow()
def greet_parent(name: str) -> dict:
    audit(f"start:{name}")
    branch = DBOS.start_workflow(greet_child, name, nested=True)
    leaf = DBOS.start_workflow(greet_child, name, nested=False)
    risky = DBOS.start_workflow(risky_child, name)
    branch.get_result()
    leaf.get_result()
    # Swallow the risky child's failure so the parent itself still succeeds —
    # gives the UI a mix of SUCCESS + ERROR branches under one parent.
    try:
        risky.get_result()
        risky_status = "ok"
    except Exception as e:
        LOG.warning("risky_child failed: %s", e)
        risky_status = "failed"
    log_greeting(f"parent complete for {name}")
    return {
        "kind": "parent",
        "name": name,
        "children_spawned": 3,
        "risky_child": risky_status,
    }


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
    LOG.info("loop_workflow result: %s", loop_workflow("argus"))
    LOG.info("greet_parent result: %s", greet_parent("argus"))
    asyncio.run(connect_to_argus())


if __name__ == "__main__":
    main()
