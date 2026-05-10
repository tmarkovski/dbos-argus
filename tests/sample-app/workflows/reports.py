"""Long-running daily report.

`generate_daily_report` runs on the `reports` queue (worker_concurrency=1) so
it serializes — when the simulator enqueues two reports a few minutes apart,
the second sits in ENQUEUED until the first finishes.
"""

from __future__ import annotations

import random

from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail


@DBOS.step()
def query_daily_metrics(date: str) -> dict:
    _pause(3, 6)
    return {
        "date": date,
        "orders": random.randint(50, 500),
        "revenue": round(random.uniform(1000, 25000), 2),
        "signups": random.randint(5, 80),
    }


@DBOS.step()
def render_summary(metrics: dict) -> str:
    _pause(2, 4)
    return (
        f"[{metrics['date']}] orders={metrics['orders']} "
        f"revenue=${metrics['revenue']:.2f} signups={metrics['signups']}"
    )


@DBOS.step()
def write_report(date: str, summary: str) -> dict:
    _pause(1, 3)
    maybe_fail(f"report-write:{date}", rate=0.10)
    return {"date": date, "path": f"/reports/{date}.json", "size": len(summary)}


@DBOS.workflow()
def generate_daily_report(date: str) -> dict:
    audit(f"report-start:{date}")
    DBOS.set_event("status", {"stage": "querying"})
    metrics = query_daily_metrics(date)
    DBOS.set_event("status", {"stage": "rendering"})
    summary = render_summary(metrics)
    DBOS.set_event("status", {"stage": "writing"})
    written = write_report(date, summary)
    log_event(f"report-done:{date}")
    return {"date": date, **metrics, "summary": summary, "report": written}
