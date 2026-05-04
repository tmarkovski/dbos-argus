"""`health` channel — pushes the same payload shape as `GET /healthz`."""

from __future__ import annotations

from typing import Any

from ...db import db
from ..channel import BroadcastChannel


class HealthChannel(BroadcastChannel):
    name = "health"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        # Hash on the result of the snapshot itself — health probes are cheap
        # enough that we don't need a separate "did anything change?" query.
        # Returning `NoCursor` from the base class would also work; this just
        # lets us de-dupe `update` broadcasts when the DB stays up.
        return await self._snapshot()

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Cursor already produced the payload; recompute to keep the API
        # symmetrical with other channels (cursor is meant to be cheap, but
        # our cursor IS the snapshot here, so we just call it again).
        return await self._snapshot()

    async def _snapshot(self) -> dict[str, str]:
        db_up = True
        db_error: str | None = None
        try:
            await db.healthcheck()
        except Exception as e:
            db_up = False
            db_error = str(e)
        body: dict[str, str] = {
            "status": "ok" if db_up else "degraded",
            "database": "up" if db_up else "down",
            "database_url": db.display_url,
        }
        if db_error is not None:
            body["database_error"] = db_error
        return body
