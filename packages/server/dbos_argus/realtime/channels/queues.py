"""`queues` channel — pushes the same payload shape as `GET /api/queues`."""

from __future__ import annotations

from typing import Any

from ...db import db
from ..channel import BroadcastChannel


class QueuesChannel(BroadcastChannel):
    name = "queues"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return await db.queues_cursor()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        from ...main import fetch_queues

        items = await fetch_queues()
        return [it.model_dump(mode="json") for it in items]
