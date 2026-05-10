"""Scheduled workflows for the Argus dev fixture.

Models a small SaaS platform's recurring maintenance work:

- `rollup-platform-metrics` — every 5m. Aggregate platform KPIs.
- `sweep-abandoned-carts` — every 5m. Find stale carts, enqueue recovery
  campaigns onto the `emails` queue.
- `reconcile-inventory` — every 15m. Reconcile inventory snapshots.

`argus-scheduler` imports this module to own the cron tick loop and the
`workflow_schedules` rows. Each schedule is registered with `queue_name="metrics"`,
so a tick enqueues a workflow onto the `metrics` queue rather than running
locally — execution belongs to `argus-metrics-runner`.

Uses the modern `DBOS.create_schedule(...)` API. The decorator-based
`@DBOS.scheduled(...)` form is deprecated upstream and doesn't persist to
`dbos.workflow_schedules`.
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import datetime
from typing import Any

from _dbos_setup import QUEUES
from dbos import DBOS
from workflows import audit, log_event, send_campaign

METRICS_QUEUE_NAME = "metrics"

# (schedule_name, cron, workflow_fn_name). Workflow name is resolved against
# `_WORKFLOWS_BY_NAME` so the table stays readable.
SCHEDULES: tuple[tuple[str, str, str], ...] = (
    ("rollup-platform-metrics", "*/5 * * * *", "rollup_platform_metrics"),
    ("sweep-abandoned-carts", "*/5 * * * *", "sweep_abandoned_carts"),
    ("reconcile-inventory", "*/15 * * * *", "reconcile_inventory"),
)

# Schedules previous versions of the demo registered. `register_schedules()`
# deletes any still in the DB so the dashboard doesn't show orphaned rows.
LEGACY_SCHEDULE_NAMES: tuple[str, ...] = ("demo-heartbeat",)


@DBOS.step()
def compute_metrics_snapshot() -> dict[str, Any]:
    """Pretend to aggregate platform KPIs. Recorded as a step so the dashboard
    can show the snapshot per run."""
    time.sleep(random.uniform(0.5, 2.0))
    return {
        "active_users": random.randint(8_000, 12_000),
        "orders_open": random.randint(100, 400),
        "revenue_24h": round(random.uniform(50_000, 120_000), 2),
        "error_rate_pct": round(random.uniform(0.1, 3.0), 2),
    }


@DBOS.step()
def find_abandoned_carts() -> list[str]:
    """Return a small batch of pretend cart IDs that have been idle > 1h."""
    time.sleep(random.uniform(0.5, 1.5))
    count = random.randint(0, 5)
    return [f"cart-{uuid.uuid4().hex[:6]}" for _ in range(count)]


@DBOS.step()
def reconcile_inventory_snapshot() -> dict[str, int]:
    """Pretend to diff the local inventory cache against the warehouse system."""
    time.sleep(random.uniform(2.0, 6.0))
    return {
        "skus_checked": random.randint(500, 2_000),
        "deltas_applied": random.randint(0, 25),
    }


@DBOS.workflow()
def rollup_platform_metrics(scheduled_at: datetime, context: Any = None) -> None:
    audit(f"metrics-rollup:{scheduled_at.isoformat()}")
    snapshot = compute_metrics_snapshot()
    log_event(f"metrics rollup ({scheduled_at.isoformat()}): {snapshot}")


@DBOS.workflow()
def sweep_abandoned_carts(scheduled_at: datetime, context: Any = None) -> None:
    audit(f"cart-sweep:{scheduled_at.isoformat()}")
    cart_ids = find_abandoned_carts()
    # Hand each recovery off to the campaigns engine, on the emails queue.
    # The dashboard then shows scheduler → metrics queue → emails fan-out.
    for cart_id in cart_ids:
        QUEUES["emails"].enqueue(send_campaign, f"cart-recovery-{cart_id}", 1)
    log_event(f"swept {len(cart_ids)} abandoned carts ({scheduled_at.isoformat()})")


@DBOS.workflow()
def reconcile_inventory(scheduled_at: datetime, context: Any = None) -> None:
    audit(f"inventory-reconcile:{scheduled_at.isoformat()}")
    result = reconcile_inventory_snapshot()
    log_event(f"inventory reconciled ({scheduled_at.isoformat()}): {result}")


_WORKFLOWS_BY_NAME: dict[str, Any] = {
    "rollup_platform_metrics": rollup_platform_metrics,
    "sweep_abandoned_carts": sweep_abandoned_carts,
    "reconcile_inventory": reconcile_inventory,
}


def register_schedules() -> None:
    """Idempotent — make `dbos.workflow_schedules` match the table above.

    Drops any legacy schedule rows the demo no longer owns, then upserts each
    current schedule. If a row already exists with matching cadence + queue
    it's left alone; otherwise it's deleted and recreated.
    """
    existing = {s["schedule_name"]: s for s in DBOS.list_schedules()}

    for legacy_name in LEGACY_SCHEDULE_NAMES:
        if legacy_name in existing:
            DBOS.delete_schedule(legacy_name)

    for schedule_name, cron, workflow_name in SCHEDULES:
        wf = _WORKFLOWS_BY_NAME[workflow_name]
        current = existing.get(schedule_name)
        if (
            current is not None
            and current["schedule"] == cron
            and current.get("queue_name") == METRICS_QUEUE_NAME
        ):
            continue
        if current is not None:
            DBOS.delete_schedule(schedule_name)
        DBOS.create_schedule(
            schedule_name=schedule_name,
            workflow_fn=wf,
            schedule=cron,
            queue_name=METRICS_QUEUE_NAME,
        )
