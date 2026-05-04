"""`stats.timeseries` channel — pushes `GET /api/stats/timeseries` payloads.

Params: `{range: "24h" | "7d" | "30d"}` — defaults to "7d".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

from ...db import db
from ..channel import KeyedChannel

_VALID_RANGES = {"24h", "7d", "30d"}


class StatsTimeseriesChannel(KeyedChannel):
    # Uses a dotted name to nest under `stats` semantically without nesting
    # actual modules. Clients subscribe by `channel: "stats.timeseries"`.
    name = "stats.timeseries"

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        raw = params or {}
        unknown = set(raw) - {"range"}
        if unknown:
            raise ValueError(f"unknown params: {sorted(unknown)}")
        rng = raw.get("range", "7d")
        if rng not in _VALID_RANGES:
            raise ValueError(f"range must be one of {sorted(_VALID_RANGES)}")
        return {"range": rng}

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        # Coarse signal — bucket counts can only change when workflow_status
        # rows arrive. Layer a minute-level tick on top so the bucket window
        # rolls forward even when no new workflows arrive.
        minute_tick = int(datetime.now(UTC).timestamp() // 60)
        base = await db.timeseries_cursor()
        return (*base, minute_tick)

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_throughput

        rng = (params or {}).get("range", "7d")
        items = await fetch_throughput(cast(Literal["24h", "7d", "30d"], rng))
        return [it.model_dump(mode="json") for it in items]
