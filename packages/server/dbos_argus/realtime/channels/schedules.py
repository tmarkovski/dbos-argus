"""`schedules` channel — pushes the same payload shape as `GET /api/schedules`."""

from __future__ import annotations

from typing import Any

from ...db import db
from ..channel import BroadcastChannel


class SchedulesChannel(BroadcastChannel):
    name = "schedules"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return await db.schedules_cursor()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_schedules

        items = await fetch_schedules()
        return [it.model_dump(mode="json") for it in items]
