"""Sample DBOS Transact app used to seed Argus's local Postgres with workflow data.

Run manually:

    cd tests/sample-app
    uv sync
    uv run python main.py

The app writes workflow rows into `dbos.workflow_status` (and friends) in the
Postgres specified by `DBOS_SYSTEM_DATABASE_URL`. Argus then reads from that
same database to render the workflow graph.
"""

from __future__ import annotations

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

DBOS_SYSTEM_DB = os.environ.get(
    "DBOS_SYSTEM_DATABASE_URL", "postgresql://argus:argus@localhost:5432/argus"
)
DBOS(config={"name": "hello-workflow", "system_database_url": DBOS_SYSTEM_DB})


@DBOS.step()
def validate_order(order_id: str) -> dict:
    time.sleep(0.08)
    return {"order_id": order_id, "valid": True, "items_count": 3}


@DBOS.step()
def compute_total(item_count: int, region: str) -> dict:
    time.sleep(0.04)
    rate = {"us": 1.0, "eu": 0.85, "uk": 0.78}.get(region, 1.0)
    subtotal = item_count * 19.99
    return {
        "region": region,
        "item_count": item_count,
        "subtotal": subtotal,
        "total": round(subtotal * rate, 2),
    }


@DBOS.step()
def log_event(event: str) -> None:
    time.sleep(0.02)
    LOG.info("event: %s", event)


@DBOS.step()
def audit(action: str) -> dict:
    time.sleep(0.01)
    return {"action": action, "actor": "fulfillment"}


@DBOS.step()
def package_items(order_id: str) -> str:
    time.sleep(0.01)
    return f"PKG-{order_id.upper()}"


@DBOS.step()
def count_items(label: str) -> int:
    time.sleep(0.01)
    return len(label)


@DBOS.step()
def run_fraud_scan(order_id: str) -> None:
    time.sleep(0.02)
    raise ValueError(f"suspicious activity detected for order {order_id!r}")


@DBOS.workflow()
def fraud_check(order_id: str) -> dict:
    # Always blows up inside a step, so both the step and this workflow
    # land in ERROR state — gives the UI a failing branch to display.
    run_fraud_scan(order_id)
    return {"order_id": order_id, "cleared": True}


@DBOS.workflow()
def process_order(order_id: str) -> dict:
    validation = validate_order(order_id)
    pricing = compute_total(validation["items_count"], "eu")
    label = package_items(order_id)
    size = count_items(label)
    log_event(f"processed:{order_id}")
    audit(f"order:{order_id}")
    return {
        "order_id": order_id,
        "items": validation["items_count"],
        "total": pricing["total"],
        "label": label,
        "label_length": size,
        "region": pricing["region"],
    }


@DBOS.workflow()
def send_campaign(campaign_id: str, count: int = 5) -> dict:
    deliveries = [package_items(f"{campaign_id}-{i}") for i in range(count)]
    return {"campaign_id": campaign_id, "deliveries": deliveries, "count": count}


@DBOS.workflow()
def prepare_shipment(order_id: str, nested: bool = False) -> dict:
    validation = validate_order(order_id)
    if nested:
        inner = DBOS.start_workflow(prepare_shipment, order_id, nested=False)
        inner.get_result()  # wait for the child without folding it into our output
    log_event(f"shipment-ready:{order_id}")
    return {
        "kind": "shipment",
        "order_id": order_id,
        "items": validation["items_count"],
        "nested": nested,
    }


@DBOS.workflow()
def reconcile_inventory(order_id: str) -> dict:
    # A few quick steps, then a long sleep so the workflow stays in PENDING
    # state for the UI to display alongside finished siblings.
    audit(f"reconcile-start:{order_id}")
    validate_order(order_id)
    log_event(f"awaiting nightly reconciliation for {order_id}")
    DBOS.sleep(86400)  # 24h — effectively "still running" for the demo
    return {"kind": "reconcile", "order_id": order_id, "completed": True}


@DBOS.workflow()
def fulfill_order(order_id: str) -> dict:
    audit(f"fulfill-start:{order_id}")
    nested_branch = DBOS.start_workflow(prepare_shipment, order_id, nested=True)
    leaf_branch = DBOS.start_workflow(prepare_shipment, order_id, nested=False)
    fraud = DBOS.start_workflow(fraud_check, order_id)
    # Fire-and-forget: this child sleeps for a day and we never get_result it,
    # so it stays PENDING in the UI long after the parent finishes.
    DBOS.start_workflow(reconcile_inventory, order_id)
    nested_branch.get_result()
    leaf_branch.get_result()
    # Swallow the fraud check's failure so the parent itself still succeeds —
    # gives the UI a mix of SUCCESS + ERROR branches under one parent.
    try:
        fraud.get_result()
        fraud_status = "cleared"
    except Exception as e:
        LOG.warning("fraud_check failed: %s", e)
        fraud_status = "flagged"
    log_event(f"fulfillment complete for {order_id}")
    return {
        "kind": "fulfillment",
        "order_id": order_id,
        "children_spawned": 4,
        "fraud_check": fraud_status,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    LOG.info("process_order result: %s", process_order("ord-1001"))
    LOG.info("send_campaign result: %s", send_campaign("spring-sale", 20))
    LOG.info("fulfill_order result: %s", fulfill_order("ord-1001"))


if __name__ == "__main__":
    main()
