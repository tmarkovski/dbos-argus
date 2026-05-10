"""Shared DBOS construction for the simulator, runner, ops, and scheduler CLIs.

Every process in the demo:

1. Calls `init_dbos(executor_id, worker_queue=...)` exactly once. This constructs
   the DBOS singleton and configures `DBOS.listen_queues([...])` (which must run
   BEFORE `DBOS.launch()`).
2. Imports `workflows` so the @DBOS.workflow decorators register.
3. Calls `DBOS.launch()`.
4. Calls `register_queues()` to persist every queue's config into `dbos.queues`
   (must run AFTER `DBOS.launch()` — `register_queue` needs `_sys_db`).

`worker_queue` names the one queue this process actually drains; pass `None` for
enqueue-only processes (the simulator, ops). The filter is enforced via
`DBOS.listen_queues`, not by zeroing out worker_concurrency.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dbos import DBOS, Queue
from dotenv import load_dotenv

DEFAULT_DB_URL = "postgresql://argus:argus@localhost:5432/argus"
ENV_PATH = Path(__file__).resolve().parent / ".env"

# Queue name → worker_concurrency the queue is registered with. Every process
# registers every queue with the same config (idempotent upsert), so the only
# variable across processes is which queue each one drains.
QUEUE_CONFIGS: dict[str, int] = {
    "onboarding": 5,
    "orders": 10,
    "billing": 5,
    "emails": 20,
    "payments": 2,
    "returns": 5,
    "reports": 1,
    "metrics": 50,
}

# Queues previous versions of the demo registered. `register_queues()` deletes
# any still in `dbos.queues` so the dashboard doesn't show orphaned rows.
LEGACY_QUEUE_NAMES: tuple[str, ...] = ("heartbeats",)

# Populated by `register_queues()` (post-launch). Workflow code reaches in here
# for cross-queue enqueue.
QUEUES: dict[str, Queue] = {}


# Messages DBOS raises when a workflow/step tries to access the system database
# after `DBOS.destroy()` has torn it down. This happens to any workflow that's
# still blocked on `recv` (60–120s timeouts in this demo) when a `argus-runner`
# worker reaches its drain duration: the workflow can't finish inside the
# `workflow_completion_timeout_sec` grace window, the destroy proceeds anyway,
# and the next access crashes. The workflow is left in PENDING and gets
# recovered cleanly on the next worker spawn — the stderr noise is purely
# cosmetic, so we filter it out.
_SHUTDOWN_RACE_MESSAGES = (
    "System database accessed before DBOS was launched",
    "No DBOS was created yet",
)


class _SimulatedFailureFilter(logging.Filter):
    """Drop DBOS's per-workflow-exception traceback log when the cause is a
    `SimulatedFailure` raised by `maybe_fail`, or when it's the known
    shutdown-race `DBOSException` chain. In both cases the workflow still
    transitions to ERROR/PENDING in `dbos.workflow_status` and DBOS recovery
    picks it up — only the noisy stderr traceback is suppressed so the demo
    console stays readable.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc is None:
            return True
        # Import lazily to avoid pulling the workflows package at module load.
        from workflows.common import SimulatedFailure

        if isinstance(exc, SimulatedFailure):
            return False
        # Walk the exception chain so the wrapped cause is checked too.
        cur: BaseException | None = exc
        while cur is not None:
            msg = str(cur)
            if any(m in msg for m in _SHUTDOWN_RACE_MESSAGES):
                return False
            cur = cur.__cause__ or cur.__context__
        return True


_SIMULATED_FAILURE_FILTER_INSTALLED = False


def _install_simulated_failure_filter() -> None:
    global _SIMULATED_FAILURE_FILTER_INSTALLED
    if _SIMULATED_FAILURE_FILTER_INSTALLED:
        return
    logging.getLogger("dbos").addFilter(_SimulatedFailureFilter())
    _SIMULATED_FAILURE_FILTER_INSTALLED = True


def init_dbos(
    executor_id: str,
    app_name: str = "demo",
    *,
    worker_queue: str | None = None,
) -> None:
    """Construct the DBOS singleton and configure the queue listen filter.

    `worker_queue` names the one queue this process should dequeue from. Pass
    `None` for enqueue-only processes — they'll be configured with an empty
    listen list so no worker threads spawn.
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

    _install_simulated_failure_filter()

    if worker_queue is not None and worker_queue not in QUEUE_CONFIGS:
        raise ValueError(
            f"worker_queue={worker_queue!r} is not in QUEUE_CONFIGS "
            f"(known: {sorted(QUEUE_CONFIGS)})"
        )

    DBOS.listen_queues([worker_queue] if worker_queue is not None else [])


def register_queues() -> None:
    """Upsert every queue in `QUEUE_CONFIGS` into `dbos.queues`.

    Must run AFTER `DBOS.launch()` — `DBOS.register_queue` writes through
    `_sys_db`, which raises if accessed pre-launch. Uses
    `on_conflict="always_update"` so a process started with a newer config
    overwrites whatever's currently in the table. Drops legacy queue rows
    the demo no longer owns.
    """
    # `delete_queue` isn't on the public DBOS surface; reach into the singleton
    # via the same private helper `DBOS.register_queue` uses internally.
    from dbos._dbos import _get_dbos_instance

    sys_db = _get_dbos_instance()._sys_db
    for legacy_name in LEGACY_QUEUE_NAMES:
        sys_db.delete_queue(legacy_name)

    QUEUES.clear()
    for name, concurrency in QUEUE_CONFIGS.items():
        QUEUES[name] = DBOS.register_queue(
            name,
            worker_concurrency=concurrency,
            on_conflict="always_update",
        )
