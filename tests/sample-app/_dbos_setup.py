"""Shared DBOS construction for the runner and ops CLIs.

Loads env vars from `tests/sample-app/.env` (the one next to this file), then
constructs the DBOS singleton with the given executor_id. If
`DBOS_CONDUCTOR_KEY` is set, the process is connected to DBOS Conductor and
DBOS will override the executor_id with a generated UUID at launch — see
_dbos.py:524.

Also defines the demo queue. The runner registers it with default (unlimited)
worker concurrency so it dequeues and runs queued workflows. The ops CLI
registers it with `worker_concurrency=0` so it can `DEMO_QUEUE.enqueue(...)`
but its own queue worker never claims a row — no race with the runner.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dbos import DBOS, Queue
from dotenv import load_dotenv

DEFAULT_DB_URL = "postgresql://argus:argus@localhost:5432/argus"
ENV_PATH = Path(__file__).resolve().parent / ".env"

DEMO_QUEUE_NAME = "argus-demo-queue"

# Populated by `init_dbos`; importers should reference it after init.
DEMO_QUEUE: Queue | None = None


def init_dbos(
    executor_id: str,
    app_name: str = "argus-demo",
    *,
    is_worker: bool = True,
) -> None:
    """Construct the DBOS singleton + the demo queue. Call once per process.

    `is_worker=False` registers the queue with `worker_concurrency=0`, so this
    process can enqueue but never dequeues — used by the ops CLI.
    """
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH)

    db_url = os.environ.get("DBOS_SYSTEM_DATABASE_URL", DEFAULT_DB_URL)
    conductor_key = os.environ.get("DBOS_CONDUCTOR_KEY")

    kwargs: dict = {
        "config": {
            "name": app_name,
            "system_database_url": db_url,
            "executor_id": executor_id,
        }
    }
    if conductor_key:
        kwargs["conductor_key"] = conductor_key
        print(
            f"[{executor_id}] DBOS_CONDUCTOR_KEY detected (…{conductor_key[-8:]}) — "
            f"connecting to Conductor as app_name={app_name!r}",
            file=sys.stderr,
        )
    else:
        print(
            f"[{executor_id}] no DBOS_CONDUCTOR_KEY — running local-only (app_name={app_name!r})",
            file=sys.stderr,
        )

    DBOS(**kwargs)

    global DEMO_QUEUE
    DEMO_QUEUE = Queue(
        DEMO_QUEUE_NAME,
        worker_concurrency=None if is_worker else 0,
    )
