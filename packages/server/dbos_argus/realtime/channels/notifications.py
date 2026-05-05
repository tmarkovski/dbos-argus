"""`notifications` channel — pushes the same payload shape as `GET /api/notifications`.

Params (all optional):
  - consumed: bool | None
  - destination_uuid: str | None
  - topic: str | None
  - limit: int (1..500, default 200)
"""

from __future__ import annotations

from typing import Any

from ...db import db
from ...db.rows import NotificationFilters
from ..channel import KeyedChannel

_ALLOWED_PARAM_KEYS = {"consumed", "destination_uuid", "topic", "limit"}


def _normalize(params: dict[str, Any] | None) -> dict[str, Any]:
    raw = params or {}
    unknown = set(raw) - _ALLOWED_PARAM_KEYS
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    consumed = raw.get("consumed")
    if consumed is not None and not isinstance(consumed, bool):
        raise ValueError("consumed must be a bool")

    destination_uuid = raw.get("destination_uuid")
    if destination_uuid is not None and not isinstance(destination_uuid, str):
        raise ValueError("destination_uuid must be a string")

    topic = raw.get("topic")
    if topic is not None and not isinstance(topic, str):
        raise ValueError("topic must be a string")

    limit = raw.get("limit", 200)
    if not isinstance(limit, int) or limit < 1 or limit > 500:
        raise ValueError("limit must be an int in 1..500")

    return {
        "consumed": consumed,
        "destination_uuid": destination_uuid or None,
        "topic": topic or None,
        "limit": limit,
    }


class NotificationsChannel(KeyedChannel):
    name = "notifications"

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        return _normalize(params)

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        # Coarse global probe: per-filter aggregates would be close to
        # snapshot work, so we accept slight over-snapshotting.
        return await db.notifications_cursor()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_notifications

        normalized = params or {}
        items = await fetch_notifications(
            NotificationFilters(
                limit=normalized.get("limit", 200),
                consumed=normalized.get("consumed"),
                destination_uuid=normalized.get("destination_uuid"),
                topic=normalized.get("topic"),
            )
        )
        return [it.model_dump(mode="json") for it in items]
