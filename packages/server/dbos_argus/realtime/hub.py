"""Hub, Connection, Subscription, Poller.

The hub owns the channel registry and maps each subscription to a `Poller`.
Pollers hold a refcounted set of subscriptions; when the last subscriber
leaves, the poller's loop is cancelled and removed from the hub.

Connections own a bounded outbound queue served by a writer task — a slow
or hung client will fill its queue and get force-closed without blocking
any poller.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .channel import BroadcastChannel, Channel, KeyedChannel, NoCursor
from .protocol import (
    AckMessage,
    ErrorMessage,
    ServerMessage,
    SnapshotMessage,
    UpdateMessage,
)

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger("dbos_argus.realtime")


# Per-connection outbound queue. Sized so a healthy client never sees backpressure
# (each poller emits at most ~one message per tick), but small enough that a
# stuck client gets disconnected promptly instead of bloating server memory.
_OUTBOUND_QUEUE_LIMIT = 128


# `eq=False` keeps these identity-hashable so the hub can store them in
# `set`s and `dict`s. The dataclass-generated `__eq__` would set
# `__hash__ = None`, which we don't want for these mutable bookkeeping types.
@dataclass(eq=False)
class Subscription:
    sub_id: str
    channel: Channel
    params: dict[str, Any] | None
    connection: Connection
    poller: Poller | None = None


def _make_out_queue() -> asyncio.Queue[ServerMessage]:
    return asyncio.Queue(_OUTBOUND_QUEUE_LIMIT)


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    subs: dict[str, Subscription] = field(default_factory=dict)
    out_queue: asyncio.Queue[ServerMessage] = field(default_factory=_make_out_queue)
    closed: bool = False

    def enqueue(self, msg: ServerMessage) -> bool:
        """Try to enqueue `msg` for sending. Returns False if the queue is
        full — caller should close the connection rather than block.
        """
        if self.closed:
            return False
        try:
            self.out_queue.put_nowait(msg)
            return True
        except asyncio.QueueFull:
            return False


class Poller:
    """Drives one channel + (for keyed channels) one params hash.

    Lifecycle:
      - Created on first subscribe; immediately starts a background task.
      - Loop body: `cursor()` → if changed, `snapshot()` → broadcast.
      - On `add(sub)`: if a snapshot is already cached, send it directly to
        the new subscriber; otherwise the next loop tick will broadcast.
      - On `remove(sub)`: when the subscription set is empty, cancels its
        own task and signals the hub to forget it.
    """

    def __init__(
        self,
        *,
        channel: Channel,
        params: dict[str, Any] | None,
        interval: float,
        on_empty: Callable[[Poller], None],
    ) -> None:
        self.channel = channel
        self.params = params
        self.interval = interval
        self._on_empty = on_empty

        self.subs: set[Subscription] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._wake = asyncio.Event()

        self._last_cursor: Any = _SENTINEL
        self._last_snapshot: Any = _SENTINEL
        self._last_error: str | None = None

    @property
    def has_snapshot(self) -> bool:
        return self._last_snapshot is not _SENTINEL

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"poller:{self.channel.name}")

    def add(self, sub: Subscription) -> None:
        self.subs.add(sub)
        if self.has_snapshot:
            sub.connection.enqueue(
                SnapshotMessage(
                    sub_id=sub.sub_id,
                    channel=self.channel.name,
                    data=self._last_snapshot,
                )
            )

    def remove(self, sub: Subscription) -> None:
        self.subs.discard(sub)
        if not self.subs:
            self._stopping = True
            self._wake.set()
            if self._task is not None:
                self._task.cancel()
            self._on_empty(self)

    def _broadcast_snapshot(self) -> None:
        """Send the cached snapshot as a `snapshot` message to every sub."""
        for sub in list(self.subs):
            sub.connection.enqueue(
                SnapshotMessage(
                    sub_id=sub.sub_id,
                    channel=self.channel.name,
                    data=self._last_snapshot,
                )
            )

    def _broadcast_update(self) -> None:
        for sub in list(self.subs):
            sub.connection.enqueue(
                UpdateMessage(
                    sub_id=sub.sub_id,
                    channel=self.channel.name,
                    data=self._last_snapshot,
                )
            )

    def _broadcast_error(self, code: str, message: str) -> None:
        for sub in list(self.subs):
            sub.connection.enqueue(ErrorMessage(sub_id=sub.sub_id, code=code, message=message))

    async def _run(self) -> None:
        # First tick happens immediately so the first subscriber doesn't wait
        # one full interval for their initial snapshot. Subsequent ticks honor
        # `self.interval`.
        first = True
        while not self._stopping:
            if not first:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
                    self._wake.clear()
                except TimeoutError:
                    pass
                if self._stopping:
                    return
            first = False

            try:
                cursor = await self.channel.cursor(self.params)
            except Exception as e:
                # Cursor errors are usually transient (DB blip). Log, broadcast
                # once if subscribers haven't seen this error yet, then keep
                # ticking.
                if self._last_error != str(e):
                    logger.warning("realtime: cursor failed for %s: %s", self.channel.name, e)
                    self._broadcast_error("cursor_failed", str(e))
                    self._last_error = str(e)
                continue

            if cursor is not NoCursor and cursor == self._last_cursor and self.has_snapshot:
                # No change since last broadcast — skip the heavy query.
                continue

            try:
                snapshot = await self.channel.snapshot(self.params)
            except Exception as e:
                if self._last_error != str(e):
                    logger.warning("realtime: snapshot failed for %s: %s", self.channel.name, e)
                    self._broadcast_error("snapshot_failed", str(e))
                    self._last_error = str(e)
                continue

            self._last_error = None
            had_snapshot = self.has_snapshot
            prev_snapshot = self._last_snapshot
            self._last_cursor = cursor
            self._last_snapshot = snapshot
            if had_snapshot:
                if snapshot == prev_snapshot:
                    # Cursor-less channels (workflow, health) re-snapshot every
                    # tick; suppress the update when the payload is identical so
                    # clients don't re-render needlessly. xyflow in particular
                    # restarts edge-dash animations on every props update.
                    continue
                self._broadcast_update()
            else:
                # First snapshot for this poller — broadcast as `snapshot`.
                self._broadcast_snapshot()


_SENTINEL: Any = object()


class RealtimeHub:
    """Central registry: channels in, connections + subscriptions out.

    The hub does not own the WebSocket I/O loop — that's the FastAPI
    endpoint's job. The hub only manages subscriptions and pollers.
    """

    def __init__(
        self,
        *,
        default_interval_ms: int = 2000,
        max_subs_per_conn: int = 64,
    ) -> None:
        self.channels: dict[str, Channel] = {}
        # Per-channel interval overrides, in seconds. Channels not listed use
        # `default_interval_s`.
        self._intervals: dict[str, float] = {}
        self._default_interval_s = default_interval_ms / 1000.0
        self._max_subs_per_conn = max_subs_per_conn

        self._connections: set[Connection] = set()
        # (channel_name, params_key_or_None) -> Poller
        self._pollers: dict[tuple[str, str], Poller] = {}

    def register_channel(self, channel: Channel, *, interval_ms: int | None = None) -> None:
        if channel.name in self.channels:
            raise ValueError(f"channel already registered: {channel.name}")
        self.channels[channel.name] = channel
        if interval_ms is not None:
            self._intervals[channel.name] = interval_ms / 1000.0

    # Connection bookkeeping --------------------------------------------------

    def attach(self, conn: Connection) -> None:
        self._connections.add(conn)

    def detach(self, conn: Connection) -> None:
        # Drop every subscription on this connection. Iterate over a copy
        # because `unsubscribe` mutates `conn.subs`.
        for sub_id in list(conn.subs.keys()):
            self.unsubscribe(conn, sub_id, ack=False)
        conn.closed = True
        self._connections.discard(conn)

    # Subscriptions -----------------------------------------------------------

    def subscribe(
        self,
        conn: Connection,
        sub_id: str,
        channel_name: str,
        params: dict[str, Any] | None,
    ) -> None:
        if sub_id in conn.subs:
            conn.enqueue(
                ErrorMessage(
                    sub_id=sub_id,
                    code="already_subscribed",
                    message=f"sub_id '{sub_id}' is already in use on this connection",
                )
            )
            return
        if len(conn.subs) >= self._max_subs_per_conn:
            conn.enqueue(
                ErrorMessage(
                    sub_id=sub_id,
                    code="too_many_subscriptions",
                    message=f"connection exceeded max_subs={self._max_subs_per_conn}",
                )
            )
            return

        channel = self.channels.get(channel_name)
        if channel is None:
            conn.enqueue(
                ErrorMessage(
                    sub_id=sub_id,
                    code="unknown_channel",
                    message=f"no channel named '{channel_name}'",
                )
            )
            return

        try:
            normalized_params = channel.validate_params(params)
        except ValueError as e:
            conn.enqueue(ErrorMessage(sub_id=sub_id, code="invalid_params", message=str(e)))
            return

        sub = Subscription(
            sub_id=sub_id, channel=channel, params=normalized_params, connection=conn
        )
        conn.subs[sub_id] = sub
        # Ack first so clients always see ack-before-snapshot. Then attach to
        # the poller, which may immediately enqueue a cached snapshot.
        conn.enqueue(AckMessage(sub_id=sub_id, op="subscribe"))
        poller = self._get_or_start_poller(channel, normalized_params)
        sub.poller = poller
        poller.add(sub)

    def unsubscribe(self, conn: Connection, sub_id: str, *, ack: bool = True) -> None:
        sub = conn.subs.pop(sub_id, None)
        if sub is None:
            if ack:
                conn.enqueue(
                    ErrorMessage(sub_id=sub_id, code="not_subscribed", message="no such sub_id")
                )
            return
        if sub.poller is not None:
            sub.poller.remove(sub)
        if ack:
            conn.enqueue(AckMessage(sub_id=sub_id, op="unsubscribe"))

    def update_params(
        self,
        conn: Connection,
        sub_id: str,
        params: dict[str, Any] | None,
    ) -> None:
        sub = conn.subs.get(sub_id)
        if sub is None:
            conn.enqueue(
                ErrorMessage(sub_id=sub_id, code="not_subscribed", message="no such sub_id")
            )
            return
        try:
            normalized_params = sub.channel.validate_params(params)
        except ValueError as e:
            conn.enqueue(ErrorMessage(sub_id=sub_id, code="invalid_params", message=str(e)))
            return
        # Detach from current poller, re-attach to (possibly different) poller.
        old_poller = sub.poller
        sub.params = normalized_params
        new_poller = self._get_or_start_poller(sub.channel, normalized_params)
        if new_poller is old_poller:
            conn.enqueue(AckMessage(sub_id=sub_id, op="update_params"))
            return
        if old_poller is not None:
            old_poller.remove(sub)
        sub.poller = new_poller
        new_poller.add(sub)
        conn.enqueue(AckMessage(sub_id=sub_id, op="update_params"))

    # Pollers -----------------------------------------------------------------

    def _get_or_start_poller(self, channel: Channel, params: dict[str, Any] | None) -> Poller:
        if isinstance(channel, KeyedChannel):
            key = (channel.name, channel.params_key(params))
        elif isinstance(channel, BroadcastChannel):
            key = (channel.name, "")
        else:
            # Bare Channel — treat as broadcast (one poller).
            key = (channel.name, "")
        poller = self._pollers.get(key)
        if poller is None:
            interval = self._intervals.get(channel.name, self._default_interval_s)
            poller = Poller(
                channel=channel,
                params=params,
                interval=interval,
                on_empty=lambda p, k=key: self._pollers.pop(k, None),
            )
            self._pollers[key] = poller
            poller.start()
        return poller

    # Test / introspection helpers --------------------------------------------

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def poller_count(self) -> int:
        return len(self._pollers)
