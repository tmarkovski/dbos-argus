"""Returns / refunds.

`process_return` runs on the `returns` queue. Demonstrates:
- recv with timeout for ops approval (auto-approves on timeout 50/50)
- sub-workflow `issue_refund` enqueued onto `payments` (rate-limited)
- sub-workflow `restock_items`
"""

from __future__ import annotations

import random

from _dbos_setup import QUEUES
from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail

RETURN_APPROVAL_TOPIC = "return-approval"
RETURN_APPROVAL_TIMEOUT_SEC = 120


@DBOS.step()
def receive_return_request(order_id: str) -> dict:
    _pause()
    item_count = random.randint(1, 3)
    reason = random.choice(["damaged", "wrong-item", "no-longer-needed"])
    return {"order_id": order_id, "items": item_count, "reason": reason}


@DBOS.step()
def refund_step(order_id: str, amount: float) -> dict:
    _pause(2, 4)
    maybe_fail(f"refund:{order_id}", rate=0.15)
    return {
        "order_id": order_id,
        "amount": amount,
        "refund_id": f"REF-{abs(hash(order_id)) % 1_000_000:06d}",
    }


@DBOS.step()
def restock_step(order_id: str, item_count: int) -> dict:
    _pause(1, 3)
    return {"order_id": order_id, "restocked": item_count}


@DBOS.step()
def reject_return(order_id: str) -> dict:
    _pause()
    return {"order_id": order_id, "rejected": True}


@DBOS.workflow()
def issue_refund(order_id: str, amount: float) -> dict:
    audit(f"refund-start:{order_id}")
    return refund_step(order_id, amount)


@DBOS.workflow()
def restock_items(order_id: str, item_count: int) -> dict:
    audit(f"restock-start:{order_id}")
    return restock_step(order_id, item_count)


@DBOS.workflow()
def process_return(order_id: str) -> dict:
    audit(f"return-start:{order_id}")
    request = receive_return_request(order_id)
    DBOS.set_event("status", {"stage": "awaiting-approval"})

    approval = DBOS.recv(topic=RETURN_APPROVAL_TOPIC, timeout_seconds=RETURN_APPROVAL_TIMEOUT_SEC)
    if approval is None:
        # No human in the loop: auto-decide so the dashboard sees both branches.
        approved = random.random() < 0.5
        log_event(f"return-auto-decision:{order_id}:approved={approved}")
    else:
        approved = bool(approval.get("approved", True)) if isinstance(approval, dict) else True

    if not approved:
        rejected = reject_return(order_id)
        DBOS.set_event("status", {"stage": "rejected"})
        return {"order_id": order_id, "outcome": "rejected", **rejected}

    amount = round(request["items"] * 19.99, 2)
    refund_handle = QUEUES["payments"].enqueue(issue_refund, order_id, amount)
    try:
        refund = refund_handle.get_result()
    except Exception as e:
        log_event(f"refund-failed:{order_id}:{e}")
        DBOS.set_event("status", {"stage": "refund-failed"})
        return {"order_id": order_id, "outcome": "refund-failed", "items": request["items"]}

    restocked = restock_items(order_id, request["items"])
    DBOS.set_event("status", {"stage": "completed"})
    return {
        "order_id": order_id,
        "outcome": "refunded",
        "amount": refund["amount"],
        "refund_id": refund["refund_id"],
        "restocked": restocked["restocked"],
    }
