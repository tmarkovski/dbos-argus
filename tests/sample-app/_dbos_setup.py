"""Shared DBOS construction for the simulator, runner, ops, and scheduler CLIs.

Every process in the demo:

1. Calls `init_dbos(executor_id, worker_queue=...)` exactly once.
2. Then imports `workflows` so the @DBOS.workflow decorators register.

`worker_queue` controls which queue this process actually drains. The named
queue is registered with its full concurrency; every other queue is registered
with `worker_concurrency=0` so this process can enqueue but never dequeue. Pass
`worker_queue=None` for processes that only ever enqueue (the simulator, ops).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dbos import DBOS, Queue
from dotenv import load_dotenv

DEFAULT_DB_URL = "postgresql://argus:argus@localhost:5432/argus"
ENV_PATH = Path(__file__).resolve().parent / ".env"

# Queue name → worker_concurrency when this process is the worker for it.
QUEUE_CONFIGS: dict[str, int] = {
    "onboarding": 5,
    "orders": 10,
    "billing": 5,
    "emails": 20,
    "payments": 2,
    "returns": 5,
    "reports": 1,
}

# Populated by `init_dbos`. Workflow code reaches in here for cross-queue enqueue.
QUEUES: dict[str, Queue] = {}


def init_dbos(
    executor_id: str,
    app_name: str = "demo",
    *,
    worker_queue: str | None = None,
) -> None:
    """Construct the DBOS singleton and register all demo queues.

    `worker_queue` names the one queue this process actually drains. Every other
    queue gets `worker_concurrency=0` so enqueue still works but no dequeue.
    """
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH)

    db_url = os.environ.get("DBOS_SYSTEM_DATABASE_URL", DEFAULT_DB_URL)

    print(
        f"[{executor_id}] starting (app_name={app_name!r}, worker_queue={worker_queue!r})",
        file=sys.stderr,
    )

    DBOS(
        config={
            "name": app_name,
            "system_database_url": db_url,
            "executor_id": executor_id,
        }
    )

    if worker_queue is not None and worker_queue not in QUEUE_CONFIGS:
        raise ValueError(
            f"worker_queue={worker_queue!r} is not in QUEUE_CONFIGS "
            f"(known: {sorted(QUEUE_CONFIGS)})"
        )

    QUEUES.clear()
    for name, concurrency in QUEUE_CONFIGS.items():
        wc = concurrency if name == worker_queue else 0
        QUEUES[name] = Queue(name, worker_concurrency=wc)
