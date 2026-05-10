"""Marketing campaign fan-out.

`send_campaign` runs on the `emails` queue and enqueues N `deliver_message`
children back onto the same queue (concurrency=20), so they drain in parallel.
Demonstrates:
- fan-out from a parent workflow
- many ENQUEUED rows draining together
- per-child failure (~10%) without aborting the whole campaign
"""

from __future__ import annotations

import random

from _dbos_setup import QUEUES
from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail


@DBOS.step()
def render_template(campaign_id: str, recipient: str) -> str:
    _pause(0.3, 1.5)
    return f"<email campaign={campaign_id} to={recipient}>"


@DBOS.step()
def smtp_send(recipient: str, body: str) -> dict:
    _pause(0.5, 2.5)
    maybe_fail(f"smtp:{recipient}", rate=0.10)
    return {"recipient": recipient, "bytes": len(body), "delivered": True}


@DBOS.workflow()
def deliver_message(campaign_id: str, recipient: str) -> dict:
    body = render_template(campaign_id, recipient)
    return smtp_send(recipient, body)


@DBOS.workflow()
def send_campaign(campaign_id: str, recipient_count: int | None = None) -> dict:
    if recipient_count is None:
        recipient_count = random.randint(5, 15)
    audit(f"campaign-start:{campaign_id}:{recipient_count}")

    recipients = [f"user{i}@demo.example" for i in range(recipient_count)]
    handles = [QUEUES["emails"].enqueue(deliver_message, campaign_id, r) for r in recipients]

    delivered = 0
    failed = 0
    for h in handles:
        try:
            h.get_result()
            delivered += 1
        except Exception:
            failed += 1

    log_event(f"campaign-done:{campaign_id}:{delivered}/{recipient_count}")
    return {
        "campaign_id": campaign_id,
        "recipients": recipient_count,
        "delivered": delivered,
        "failed": failed,
    }
