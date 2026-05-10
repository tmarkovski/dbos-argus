"""Order fulfillment.

`fulfill_order` runs on the `orders` queue. Demonstrates:
- multi-stage pipeline with sub-workflows
- enqueueing a child onto a different (rate-limited) queue: `payments`
- recv with timeout for delivery confirmation
- ~30% chance of payment failure → graceful exit
"""

from __future__ import annotations

import random

from _dbos_setup import QUEUES
from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail

DELIVERY_CONFIRMATION_TOPIC = "delivery-confirmation"
DELIVERY_CONFIRMATION_TIMEOUT_SEC = 90


@DBOS.step()
def validate_cart(order_id: str) -> dict:
    _pause()
    item_count = random.randint(1, 6)
    return {"order_id": order_id, "items": item_count}


@DBOS.step()
def charge_card_step(order_id: str, amount: float) -> dict:
    _pause(2, 5)
    maybe_fail(f"charge:{order_id}")
    return {"order_id": order_id, "amount": amount, "auth_code": f"AUTH-{order_id[-6:].upper()}"}


@DBOS.step()
def reserve_stock_step(order_id: str, item_count: int) -> dict:
    _pause()
    return {"order_id": order_id, "reserved": item_count, "warehouse": "WH-1"}


@DBOS.step()
def pack_items(order_id: str, item_count: int) -> str:
    _pause(1, 3)
    return f"PKG-{order_id[-6:].upper()}-{item_count}"


@DBOS.step()
def hand_off_to_carrier(order_id: str, label: str) -> dict:
    _pause()
    return {"order_id": order_id, "label": label, "carrier": "ACME-FREIGHT"}


@DBOS.workflow()
def authorize_payment(order_id: str, amount: float) -> dict:
    audit(f"payment-start:{order_id}")
    result = charge_card_step(order_id, amount)
    log_event(f"payment-authorized:{order_id}")
    return result


@DBOS.workflow()
def reserve_inventory(order_id: str, item_count: int) -> dict:
    audit(f"reserve-start:{order_id}")
    result = reserve_stock_step(order_id, item_count)
    log_event(f"reserved:{order_id}")
    return result


@DBOS.workflow()
def pack_and_label(order_id: str, item_count: int) -> dict:
    audit(f"pack-start:{order_id}")
    label = pack_items(order_id, item_count)
    return {"order_id": order_id, "label": label}


@DBOS.workflow()
def fulfill_order(order_id: str) -> dict:
    """Top-level order workflow.

    Routes the payment through a separate, rate-limited `payments` queue so it
    enqueues even when the orders worker pool is wide open.
    """
    audit(f"order-start:{order_id}")
    cart = validate_cart(order_id)
    amount = round(cart["items"] * 19.99, 2)

    payment_handle = QUEUES["payments"].enqueue(authorize_payment, order_id, amount)
    try:
        payment = payment_handle.get_result()
    except Exception as e:
        log_event(f"payment-failed:{order_id}:{e}")
        DBOS.set_event("status", {"stage": "payment-failed", "order_id": order_id})
        return {"order_id": order_id, "fulfilled": False, "reason": "payment-failed"}

    DBOS.set_event("status", {"stage": "paid", "order_id": order_id})

    reserve_inventory(order_id, cart["items"])
    packed = pack_and_label(order_id, cart["items"])
    handoff = hand_off_to_carrier(order_id, packed["label"])

    DBOS.set_event("status", {"stage": "shipped", "order_id": order_id})
    confirmation = DBOS.recv(
        topic=DELIVERY_CONFIRMATION_TOPIC,
        timeout_seconds=DELIVERY_CONFIRMATION_TIMEOUT_SEC,
    )
    delivered = confirmation is not None
    DBOS.set_event(
        "status",
        {"stage": "delivered" if delivered else "in-transit", "order_id": order_id},
    )
    log_event(f"order-complete:{order_id}:delivered={delivered}")
    return {
        "order_id": order_id,
        "fulfilled": True,
        "items": cart["items"],
        "amount": payment["amount"],
        "label": packed["label"],
        "carrier": handoff["carrier"],
        "delivered": delivered,
    }
