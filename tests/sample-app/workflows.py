"""DBOS workflow + step definitions for the Argus dev fixture.

`DBOS(...)` MUST be constructed before importing this module — the @DBOS.step /
@DBOS.workflow decorators reference the global DBOS singleton at definition
time. `runner.py` imports this module after wiring up its DBOS instance; the
ops CLI does not import it (cross-executor send/cancel/resume are plain DB
operations and don't need workflow definitions).
"""

from __future__ import annotations

import logging
import random
import time

from dbos import DBOS, SetWorkflowID
from dbos._error import DBOSAwaitedWorkflowCancelledError

LOG = logging.getLogger("argus-example")

CARRIER_CONFIRMATION_TOPIC = "carrier-confirmation"
OPS_SIGNOFF_TOPIC = "ops-signoff"


# Steps reachable from `fulfill_order`'s tree sleep a random 3-10s so the
# workflow takes long enough to watch progress live in the dashboard.
def _fulfill_pause() -> None:
    time.sleep(random.uniform(3, 10))


@DBOS.step()
def validate_order(order_id: str) -> dict:
    _fulfill_pause()
    return {"order_id": order_id, "valid": True, "items_count": 3}


@DBOS.step()
def compute_total(item_count: int, region: str) -> dict:
    _fulfill_pause()
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
    _fulfill_pause()
    LOG.info("event: %s", event)


@DBOS.step()
def audit(action: str) -> dict:
    _fulfill_pause()
    return {"action": action, "actor": "fulfillment"}


@DBOS.step()
def package_items(order_id: str) -> str:
    _fulfill_pause()
    return f"PKG-{order_id.upper()}"


@DBOS.step()
def count_items(label: str) -> int:
    time.sleep(0.01)
    return len(label)


@DBOS.step()
def run_fraud_scan(order_id: str) -> None:
    _fulfill_pause()
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


@DBOS.workflow()
def dispatch_carrier(order_id: str) -> dict:
    log_event(f"carrier-dispatch:{order_id}")
    DBOS.set_event("carrier", {"order_id": order_id, "carrier": "ACME-FREIGHT", "eta_hours": 48})
    # Block on a notification from `argus-ops carrier-confirm` — demos
    # DBOS.recv (notifications) and shows the workflow resuming from PENDING
    # once the message arrives.
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
            # a confirmation message from ops, so awaiting it here would
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
    # Sleep long enough for `argus-ops cancel-stock` to hit it mid-flight.
    # `DBOS.sleep` is NOT interruptible — the thread blocks for the full
    # duration before observing the CANCELLED status.
    DBOS.sleep(30)
    log_event(f"stock-verified:{order_id}")
    return {"kind": "stock", "order_id": order_id, "in_stock": True}


@DBOS.workflow()
def reconcile_inventory(order_id: str) -> dict:
    audit(f"reconcile-start:{order_id}")
    validate_order(order_id)
    log_event(f"awaiting nightly reconciliation for {order_id}")
    # Pin a deterministic id so ops can locate this child to cancel.
    stock_workflow_id = f"{DBOS.workflow_id}-stock"
    with SetWorkflowID(stock_workflow_id):
        stock = DBOS.start_workflow(stock_check, order_id)
    try:
        stock.get_result()
    except DBOSAwaitedWorkflowCancelledError as e:
        # Demo of the cancellation feature: ops cancels `stock_check` and
        # the parent observes it here. Swallow so reconcile keeps going.
        LOG.warning("stock_check was cancelled: %s", e)
    # 30s sleep keeps this workflow PENDING long enough to be visible in the
    # dashboard. `fulfill_order` never awaits it, so the parent can move on.
    DBOS.sleep(30)
    return {"kind": "reconcile", "order_id": order_id, "completed": True}


@DBOS.workflow()
def fulfill_order(order_id: str) -> dict:
    audit(f"fulfill-start:{order_id}")
    validation = validate_order(order_id)
    # Pre-mint a deterministic id for the level-3 `dispatch_carrier` so
    # `reconcile_inventory` can `get_event` from it without waiting on
    # `prepare_shipment` to finish. Derived from the parent's id so it
    # survives workflow recovery.
    carrier_workflow_id = f"{DBOS.workflow_id}-carrier"
    nested_branch = DBOS.start_workflow(
        prepare_shipment, order_id, nested=True, carrier_workflow_id=carrier_workflow_id
    )
    log_event(f"shipment-dispatched:{order_id}")
    fraud = DBOS.start_workflow(fraud_check, order_id)
    pricing = compute_total(validation["items_count"], "us")
    # Fire-and-forget initially so it runs concurrently. Awaited at the very
    # end (after the ops-signoff recv + a 30s sleep) so the dashboard shows
    # the parent waiting on this child. Id pinned so ops can locate its
    # `stock_check` grandchild to cancel.
    reconcile_workflow_id = f"{DBOS.workflow_id}-reconcile"
    with SetWorkflowID(reconcile_workflow_id):
        reconcile = DBOS.start_workflow(reconcile_inventory, order_id)
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
    # Block waiting for an "ops-signoff" notification — `argus-ops ops-signoff`
    # unblocks it. Until then, `fulfill_order` stays PENDING in the dashboard.
    DBOS.recv(topic=OPS_SIGNOFF_TOPIC, timeout_seconds=86400)
    DBOS.sleep(30)
    reconcile.get_result()
    return {
        "kind": "fulfillment",
        "order_id": order_id,
        "children_spawned": 3,
        "fraud_check": fraud_status,
        "label": label,
        "total": pricing["total"],
    }
