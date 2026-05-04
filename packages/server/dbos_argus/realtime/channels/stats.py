"""`stats` channel — pushes the same payload shape as `GET /api/stats`."""

from __future__ import annotations

from typing import Any

from ...db import db
from ..channel import BroadcastChannel


class StatsChannel(BroadcastChannel):
    name = "stats"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        # Cheap COUNT + max(updated_at) over workflow_status, plus the
        # unconsumed-notification count. If none of these moved, the rollup
        # didn't change either. (active_schedules can drift on its own but
        # changes rarely; a dashboard reader is fine waiting for the next
        # workflow event to refresh.)
        return await db.stats_cursor()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_stats

        return (await fetch_stats()).model_dump(mode="json")
