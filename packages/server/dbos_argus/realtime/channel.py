"""Channel abstractions.

A `Channel` produces snapshots for clients. There are two flavors:

- `BroadcastChannel`: one poller per channel; identical payload to every
  subscriber (e.g. `health`, `stats` — no params, single source of truth).
- `KeyedChannel`: one poller per distinct params hash; subscribers with the
  same params share a poller (e.g. `workflows` filtered by status, `workflow`
  by id).

Both use a two-phase poll: a cheap `cursor` query gates the heavier
`snapshot` query so the DB stays cool when nothing changed.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

# Sentinel returned by `cursor()` when the channel can't compute a cheap
# change-detect (e.g. `health`). Any callsite that gets `None` should treat
# the channel as "always changed" and re-snapshot every tick.
NoCursor = None


class Channel(ABC):
    """Base channel. Subclasses are typically `BroadcastChannel` or
    `KeyedChannel` — directly subclassing `Channel` is unusual.
    """

    name: str

    @abstractmethod
    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        """Compute the full payload for this channel + params."""

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        """Cheap change-detect signal. Default: `None` (always re-snapshot)."""
        return NoCursor

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        """Override to coerce / validate client-supplied params before use.

        Default returns params unchanged. Raise `ValueError` on bad input —
        the hub turns it into an `error` message back to the client.
        """
        return params


class BroadcastChannel(Channel):
    """A channel with no params — every subscriber sees the same payload.

    Examples: `health`, `stats`. The hub keeps exactly one poller per
    BroadcastChannel and fans the cached snapshot out to all subscribers.
    """

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        if params:
            raise ValueError(f"channel '{self.name}' does not accept params")
        return None

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return NoCursor


class KeyedChannel(Channel):
    """A channel where params identify a sub-poller.

    The hub maintains one poller per `(channel.name, params_key)` and
    refcounts them — pollers shut down when their last subscriber leaves.
    Subclasses usually override `params_key` only if their params dict has
    keys whose JSON ordering isn't stable (rare; default is `sort_keys=True`).
    """

    def params_key(self, params: dict[str, Any] | None) -> str:
        """Stable hash of params used as the poller key."""
        if params is None:
            return ""
        # `default=str` lets us serialize datetime / Decimal etc. without
        # caring; the result is just an opaque key, not a payload.
        return json.dumps(params, sort_keys=True, default=str)
