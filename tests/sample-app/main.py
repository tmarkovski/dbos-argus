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
import uuid

try:
    from dbos import DBOS, SetWorkflowID
    from dbos._error import (
        DBOSAwaitedWorkflowCancelledError,
        DBOSNonExistentWorkflowError,
    )
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
def verify_address(order_id: str) -> dict:
    audit(f"verify-address:{order_id}")
    log_event(f"address-verified:{order_id}")
    return {"kind": "verify-address", "order_id": order_id, "verified": True}


CARRIER_CONFIRMATION_TOPIC = "carrier-confirmation"


@DBOS.workflow()
def dispatch_carrier(order_id: str) -> dict:
    log_event(f"carrier-dispatch:{order_id}")
    DBOS.set_event(
        "carrier", {"order_id": order_id, "carrier": "ACME-FREIGHT", "eta_hours": 48}
    )
    # Block on a notification from `main()` — demos DBOS.recv (notifications)
    # and shows the workflow resuming from PENDING once the message arrives.
    confirmation = DBOS.recv(topic=CARRIER_CONFIRMATION_TOPIC, timeout_seconds=300)
    audit(f"carrier-confirmed:{order_id}:{confirmation}")
    return {
        "kind": "carrier",
        "order_id": order_id,
        "carrier": "ACME-FREIGHT",
        "confirmation": confirmation,
    }


@DBOS.workflow()
def prepare_shipment(
    order_id: str, nested: bool = False, carrier_workflow_id: str | None = None
) -> dict:
    validation = validate_order(order_id)
    if nested:
        verify = DBOS.start_workflow(verify_address, order_id)
        if carrier_workflow_id is not None:
            # Fire-and-forget — `dispatch_carrier` blocks on a recv waiting for
            # a confirmation message from `main()`, so awaiting it here would
            # deadlock the parent.
            with SetWorkflowID(carrier_workflow_id):
                DBOS.start_workflow(dispatch_carrier, order_id)
        verify.get_result()
    log_event(f"shipment-ready:{order_id}")
    return {
        "kind": "shipment",
        "order_id": order_id,
        "items": validation["items_count"],
        "nested": nested,
    }


@DBOS.workflow()
def stock_check(order_id: str) -> dict:
    audit(f"stock-check-start:{order_id}")
    validate_order(order_id)
    # Short sleep so `main()` can cancel the workflow during it. `DBOS.sleep`
    # is NOT interruptible — the thread blocks for the full duration before
    # observing the CANCELLED status, so we can't make this much longer
    # without main() exiting before the cancellation propagates back to the
    # parent's `get_result`.
    DBOS.sleep(3)
    log_event(f"stock-verified:{order_id}")
    return {"kind": "stock", "order_id": order_id, "in_stock": True}


@DBOS.workflow()
def reconcile_inventory(order_id: str) -> dict:
    audit(f"reconcile-start:{order_id}")
    validate_order(order_id)
    log_event(f"awaiting nightly reconciliation for {order_id}")
    # Pin a deterministic id so `main()` can locate this child to cancel.
    stock_workflow_id = f"{DBOS.workflow_id}-stock"
    with SetWorkflowID(stock_workflow_id):
        stock = DBOS.start_workflow(stock_check, order_id)
    try:
        stock.get_result()
    except DBOSAwaitedWorkflowCancelledError as e:
        # Demo of the cancellation feature: `main()` cancels `stock_check` and
        # the parent observes it here. Swallow so reconcile keeps going.
        LOG.warning("stock_check was cancelled: %s", e)
    # 7d sleep keeps this workflow PENDING in the dashboard. `fulfill_order`
    # never awaits it, so the parent (and `main()`) can move on.
    DBOS.sleep(86400 * 7)
    return {"kind": "reconcile", "order_id": order_id, "completed": True}


@DBOS.workflow()
def fulfill_order(order_id: str) -> dict:
    audit(f"fulfill-start:{order_id}")
    validation = validate_order(order_id)
    # Pre-mint a deterministic id for the level-3 `dispatch_carrier` so the
    # level-2 `reconcile_inventory` can `get_event` from it without waiting on
    # `prepare_shipment` to finish. Derived from the parent's id so it survives
    # workflow recovery.
    carrier_workflow_id = f"{DBOS.workflow_id}-carrier"
    nested_branch = DBOS.start_workflow(
        prepare_shipment, order_id, nested=True, carrier_workflow_id=carrier_workflow_id
    )
    log_event(f"shipment-dispatched:{order_id}")
    fraud = DBOS.start_workflow(fraud_check, order_id)
    pricing = compute_total(validation["items_count"], "us")
    # Fire-and-forget: sleeps for 7 days so the workflow stays PENDING in the
    # dashboard alongside the completed siblings. Id pinned so `main()` can
    # locate its `stock_check` grandchild to cancel.
    reconcile_workflow_id = f"{DBOS.workflow_id}-reconcile"
    with SetWorkflowID(reconcile_workflow_id):
        DBOS.start_workflow(reconcile_inventory, order_id)
    label = package_items(order_id)
    nested_branch.get_result()
    # Swallow the fraud check's failure so the parent itself still succeeds —
    # gives the UI a mix of SUCCESS + ERROR branches under one parent.
    try:
        fraud.get_result()
        fraud_status = "cleared"
    except Exception as e:
        LOG.warning("fraud_check failed: %s", e)
        fraud_status = "flagged"
    # Block waiting for an "ops-signoff" notification that `main()` never
    # sends — leaves `fulfill_order` PENDING in the dashboard so the UI can
    # show a long-running parent workflow.
    DBOS.recv(topic="ops-signoff", timeout_seconds=86400)
    return {
        "kind": "fulfillment",
        "order_id": order_id,
        "children_spawned": 3,
        "fraud_check": fraud_status,
        "label": label,
        "total": pricing["total"],
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    DBOS.launch()
    LOG.info("process_order result: %s", process_order("ord-1001"))
    LOG.info("send_campaign result: %s", send_campaign("spring-sale", 20))

    # Pin `fulfill_order`'s workflow id so we know the derived
    # `dispatch_carrier` id (`<fulfill>-carrier`) without querying. Started
    # fire-and-forget — `fulfill_order` blocks on a never-completed `recv`
    # at the end so it stays PENDING in the dashboard, and we still want to
    # send the carrier confirmation while it's mid-flight.
    fulfill_workflow_id = f"fulfill-{uuid.uuid4().hex[:8]}"
    with SetWorkflowID(fulfill_workflow_id):
        DBOS.start_workflow(fulfill_order, "ord-1001")
    LOG.info("started fulfill_order: %s", fulfill_workflow_id)

    # `dispatch_carrier` is spawned a few async hops down inside
    # `fulfill_order`, so wait for it to register in workflow_status before
    # sending — `dbos.notifications` has a FK on `destination_uuid`.
    carrier_workflow_id = f"{fulfill_workflow_id}-carrier"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            DBOS.retrieve_workflow(carrier_workflow_id)
            break
        except DBOSNonExistentWorkflowError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"dispatch_carrier {carrier_workflow_id} never started")

    LOG.info("sending carrier confirmation to %s", carrier_workflow_id)
    DBOS.send(
        carrier_workflow_id,
        {"confirmed_by": "ops", "tracking_no": "TRK-99001"},
        topic=CARRIER_CONFIRMATION_TOPIC,
    )

    # Wait for `dispatch_carrier` to drain — it's the last child to finish
    # since the others either complete fast or pivot on its `set_event`.
    # `fulfill_order` itself stays PENDING on its trailing `recv` (we never
    # send `ops-signoff`), so we don't await it.
    DBOS.retrieve_workflow(carrier_workflow_id).get_result()
    LOG.info("dispatch_carrier completed")

    # Cancel `stock_check` mid-flight — its parent `reconcile_inventory`
    # awaits it and swallows the cancellation, then proceeds into its 7d
    # sleep. This leaves a CANCELLED workflow visible in the dashboard.
    stock_workflow_id = f"{fulfill_workflow_id}-reconcile-stock"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            DBOS.retrieve_workflow(stock_workflow_id)
            break
        except DBOSNonExistentWorkflowError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"stock_check {stock_workflow_id} never started")
    LOG.info("cancelling stock_check %s", stock_workflow_id)
    DBOS.cancel_workflow(stock_workflow_id)

    # Give `reconcile_inventory` time to observe the cancellation, persist
    # its `DBOS.getResult` row, and start its 7d sleep — the dashboard's
    # return-edge color depends on that row existing. Has to outlast
    # `stock_check`'s 3s blocking sleep, since `cancel_workflow` only takes
    # effect once the sleep wakes up.
    time.sleep(5)
    LOG.info("demo workflows queued; fulfill_order + reconcile_inventory left PENDING")


if __name__ == "__main__":
    main()
