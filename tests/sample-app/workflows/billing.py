"""Subscription billing.

`run_billing_cycle` runs on the `billing` queue. Demonstrates:
- sub-workflow `charge_card` started as a child via `DBOS.start_workflow`
  (no queue), then awaited with `handle.get_result()`
- recv with timeout for "user retried payment from billing portal"
- branch on success / dunning / delinquent
"""

from __future__ import annotations

import random

from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail

PAYMENT_RETRY_TOPIC = "payment-retry"
PAYMENT_RETRY_TIMEOUT_SEC = 90


@DBOS.step()
def lookup_subscription(account_id: str) -> dict:
    _pause()
    plan = random.choice(["starter", "pro", "team", "enterprise"])
    amount = {"starter": 9.99, "pro": 29.99, "team": 99.0, "enterprise": 499.0}[plan]
    return {"account_id": account_id, "plan": plan, "amount": amount}


@DBOS.step()
def charge_subscription(account_id: str, amount: float) -> dict:
    _pause(2, 4)
    maybe_fail(f"sub-charge:{account_id}", rate=0.4)
    return {
        "account_id": account_id,
        "amount": amount,
        "auth_code": f"BILL-{abs(hash(account_id)) % 1_000_000:06d}",
    }


@DBOS.step()
def mark_delinquent(account_id: str) -> dict:
    _pause()
    return {"account_id": account_id, "delinquent": True}


@DBOS.step()
def renew_subscription(account_id: str, plan: str) -> dict:
    _pause()
    return {"account_id": account_id, "plan": plan, "renewed": True}


@DBOS.workflow()
def charge_card(account_id: str, amount: float) -> dict:
    audit(f"sub-charge-start:{account_id}")
    result = charge_subscription(account_id, amount)
    log_event(f"sub-charged:{account_id}")
    return result


@DBOS.workflow()
def run_billing_cycle(account_id: str) -> dict:
    audit(f"billing-start:{account_id}")
    sub = lookup_subscription(account_id)
    DBOS.set_event("status", {"stage": "charging"})

    charge_handle = DBOS.start_workflow(charge_card, account_id, sub["amount"])
    try:
        charge_handle.get_result()
        DBOS.set_event("status", {"stage": "renewed"})
        renewal = renew_subscription(account_id, sub["plan"])
        return {"account_id": account_id, "outcome": "renewed", **renewal}
    except Exception as e:
        log_event(f"sub-charge-failed:{account_id}:{e}")

    DBOS.set_event("status", {"stage": "dunning"})
    retry = DBOS.recv(topic=PAYMENT_RETRY_TOPIC, timeout_seconds=PAYMENT_RETRY_TIMEOUT_SEC)
    if retry is None:
        marked = mark_delinquent(account_id)
        DBOS.set_event("status", {"stage": "delinquent"})
        return {"account_id": account_id, "outcome": "delinquent", **marked}

    retry_handle = DBOS.start_workflow(charge_card, account_id, sub["amount"])
    try:
        retry_handle.get_result()
        DBOS.set_event("status", {"stage": "renewed"})
        renewal = renew_subscription(account_id, sub["plan"])
        return {"account_id": account_id, "outcome": "renewed-after-retry", **renewal}
    except Exception:
        marked = mark_delinquent(account_id)
        DBOS.set_event("status", {"stage": "delinquent"})
        return {"account_id": account_id, "outcome": "delinquent-after-retry", **marked}
