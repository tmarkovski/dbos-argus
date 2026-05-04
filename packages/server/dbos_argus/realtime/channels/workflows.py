"""`workflows` channel — pushes the same payload shape as `GET /api/workflows`.

Params accepted (all optional):
  - limit: int (1..200, default 50)
  - q: str | None
  - started_after: ISO-8601 string | epoch-ms int | None
  - started_before: ISO-8601 string | epoch-ms int | None
  - status: list[str] | None
  - queue_name: str | None
  - grouped: bool (default true)
  - hide_scheduled: bool (default false)

The cursor is a coarse "did anything in the workflow space change?" probe
over the entire `workflow_status` + `operation_outputs` tables rather than a
per-filter aggregate. That's a small over-snapshot when multiple narrow
filters are subscribed concurrently, but the cursor query is two indexed
COUNTs + a MAX — orders of magnitude cheaper than re-running the recursive
walk that backs the snapshot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...db import db
from ...db.rows import WorkflowFilters
from ..channel import KeyedChannel

_ALLOWED_PARAM_KEYS = {
    "limit",
    "q",
    "started_after",
    "started_before",
    "status",
    "queue_name",
    "grouped",
    "hide_scheduled",
}


def _coerce_epoch_ms(value: Any) -> int | None:
    """Accept either an int (epoch ms) or an ISO-8601 string and return ms."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # Accept the same shapes FastAPI parses for `datetime` query params.
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError as e:
            raise ValueError(f"invalid datetime: {value!r}") from e
    raise ValueError(f"expected int or ISO-8601 string, got {type(value).__name__}")


def _normalize(params: dict[str, Any] | None) -> dict[str, Any]:
    """Validate + normalize client params into a stable dict that maps 1-to-1
    to `WorkflowFilters` kwargs. Returned dict is also the params_key source,
    so equivalent client payloads (status omitted vs. status=null) collapse
    to the same poller.
    """
    raw = params or {}
    unknown = set(raw) - _ALLOWED_PARAM_KEYS
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    limit_raw = raw.get("limit", 50)
    if not isinstance(limit_raw, int) or limit_raw < 1 or limit_raw > 200:
        raise ValueError("limit must be an int in 1..200")

    q_raw = raw.get("q")
    q = q_raw.strip() if isinstance(q_raw, str) and q_raw.strip() else None

    statuses_raw = raw.get("status")
    if statuses_raw is None:
        statuses = None
    elif isinstance(statuses_raw, list) and all(isinstance(s, str) for s in statuses_raw):
        statuses = statuses_raw if statuses_raw else None
    else:
        raise ValueError("status must be a list of strings")

    queue_name = raw.get("queue_name")
    if queue_name is not None and not isinstance(queue_name, str):
        raise ValueError("queue_name must be a string")

    grouped = raw.get("grouped", True)
    if not isinstance(grouped, bool):
        raise ValueError("grouped must be a bool")

    hide_scheduled = raw.get("hide_scheduled", False)
    if not isinstance(hide_scheduled, bool):
        raise ValueError("hide_scheduled must be a bool")

    return {
        "limit": limit_raw,
        "q": q,
        "started_after_ms": _coerce_epoch_ms(raw.get("started_after")),
        "started_before_ms": _coerce_epoch_ms(raw.get("started_before")),
        "statuses": statuses,
        "queue_name": queue_name,
        "grouped": grouped,
        "hide_scheduled": hide_scheduled,
    }


class WorkflowsChannel(KeyedChannel):
    name = "workflows"

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        return _normalize(params)

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return await db.workflows_cursor()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_workflow_list

        normalized = params or {}
        filters = WorkflowFilters(
            limit=normalized.get("limit", 50),
            q=normalized.get("q"),
            started_after_ms=normalized.get("started_after_ms"),
            started_before_ms=normalized.get("started_before_ms"),
            statuses=normalized.get("statuses"),
            queue_name=normalized.get("queue_name"),
            hide_scheduled=normalized.get("hide_scheduled", False),
            grouped=normalized.get("grouped", True),
        )
        items = await fetch_workflow_list(filters)
        # JSON mode so datetimes round-trip as ISO strings, matching the REST
        # endpoint's response shape exactly.
        return [it.model_dump(mode="json") for it in items]
