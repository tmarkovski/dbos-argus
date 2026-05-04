"""Hub / poller unit tests using fake in-memory channels (no DB)."""

from __future__ import annotations

import asyncio
from typing import Any

from dbos_argus.realtime.channel import BroadcastChannel, KeyedChannel
from dbos_argus.realtime.hub import Connection, RealtimeHub
from dbos_argus.realtime.protocol import (
    AckMessage,
    ServerMessage,
    SnapshotMessage,
    UpdateMessage,
)


class _FakeWebSocket:
    """Stand-in for the FastAPI WebSocket so the hub can hand out Connections
    in tests without an actual socket. Only the attributes the hub touches
    matter — `headers`, `accept`, `send_json` aren't reached because the
    writer task isn't started in these tests."""


def _make_conn() -> Connection:
    return Connection(websocket=_FakeWebSocket())  # type: ignore[arg-type]


def _drain(conn: Connection) -> list[ServerMessage]:
    msgs: list[ServerMessage] = []
    while not conn.out_queue.empty():
        msgs.append(conn.out_queue.get_nowait())
    return msgs


class CounterChannel(BroadcastChannel):
    """Snapshot returns an incrementing tick; cursor matches snapshot so each
    poll is treated as a change. Used to verify push semantics deterministically.
    """

    name = "counter"

    def __init__(self) -> None:
        self.calls = 0

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return self.calls

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        self.calls += 1
        return {"tick": self.calls}


class StaticChannel(BroadcastChannel):
    """Cursor never changes — useful for testing the de-dupe path."""

    name = "static"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return "v1"

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        return {"value": "static"}


class ParamEchoChannel(KeyedChannel):
    """Snapshot echoes the params back. Cursor changes any time params do, so
    distinct params hashes get distinct pollers (which is what we want to
    verify), and any single poller's snapshot is stable."""

    name = "echo"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        # Stable per-params; the hub doesn't share pollers across keys, so
        # this poller's cursor never changes once initialized.
        return ("v", self.params_key(params))

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        return {"params": params or {}}


# --- Subscribe / unsubscribe ------------------------------------------------


async def test_subscribe_yields_ack_then_snapshot() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(CounterChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "counter", None)

    # The poller's first tick runs as soon as the event loop yields — it
    # has no initial sleep. Give it a chance to land.
    await asyncio.sleep(0.05)

    msgs = _drain(conn)
    assert len(msgs) == 2
    assert isinstance(msgs[0], AckMessage)
    assert msgs[0].sub_id == "s1"
    assert msgs[0].op == "subscribe"
    assert isinstance(msgs[1], SnapshotMessage)
    assert msgs[1].sub_id == "s1"
    assert msgs[1].channel == "counter"
    assert msgs[1].data == {"tick": 1}

    hub.detach(conn)


async def test_unknown_channel_emits_error() -> None:
    hub = RealtimeHub()
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "nope", None)

    msgs = _drain(conn)
    assert len(msgs) == 1
    assert msgs[0].type == "error"  # type: ignore[attr-defined]
    assert "nope" in msgs[0].message  # type: ignore[attr-defined]

    hub.detach(conn)


async def test_unsubscribe_drops_poller_on_last_subscriber() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(StaticChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "static", None)
    await asyncio.sleep(0.01)
    assert hub.poller_count == 1

    hub.unsubscribe(conn, "s1")
    # Poller is removed synchronously from the hub bookkeeping.
    assert hub.poller_count == 0

    hub.detach(conn)


async def test_broadcast_channel_shares_one_poller() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(StaticChannel())
    conn1 = _make_conn()
    conn2 = _make_conn()
    hub.attach(conn1)
    hub.attach(conn2)

    hub.subscribe(conn1, "a", "static", None)
    hub.subscribe(conn2, "b", "static", None)
    assert hub.poller_count == 1

    # Both connections receive a snapshot.
    await asyncio.sleep(0.05)
    msgs1 = [m for m in _drain(conn1) if isinstance(m, SnapshotMessage)]
    msgs2 = [m for m in _drain(conn2) if isinstance(m, SnapshotMessage)]
    assert len(msgs1) == 1 and len(msgs2) == 1
    assert msgs1[0].data == {"value": "static"} == msgs2[0].data

    hub.detach(conn1)
    hub.detach(conn2)


async def test_keyed_channel_separates_pollers_by_params() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(ParamEchoChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "echo", {"id": "a"})
    hub.subscribe(conn, "s2", "echo", {"id": "b"})
    hub.subscribe(conn, "s3", "echo", {"id": "a"})  # shares with s1

    assert hub.poller_count == 2

    hub.detach(conn)


# --- update_params ----------------------------------------------------------


async def test_update_params_moves_subscription_to_new_poller() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(ParamEchoChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "echo", {"id": "a"})
    await asyncio.sleep(0.05)
    _drain(conn)  # discard ack + initial snapshot

    hub.update_params(conn, "s1", {"id": "b"})
    await asyncio.sleep(0.05)

    msgs = _drain(conn)
    # Expect an ack and a fresh snapshot for the new params.
    types = [m.type for m in msgs]  # type: ignore[attr-defined]
    assert "ack" in types
    snapshots = [m for m in msgs if isinstance(m, SnapshotMessage)]
    assert any(m.data == {"params": {"id": "b"}} for m in snapshots)

    # Old poller should be gone, new one in its place.
    assert hub.poller_count == 1

    hub.detach(conn)


async def test_update_params_same_key_is_noop_for_pollers() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(ParamEchoChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "echo", {"id": "a"})
    await asyncio.sleep(0.05)
    _drain(conn)

    hub.update_params(conn, "s1", {"id": "a"})
    msgs = _drain(conn)
    # Just an ack, no extra snapshot, and the existing poller stays.
    assert [m.type for m in msgs] == ["ack"]  # type: ignore[attr-defined]
    assert hub.poller_count == 1

    hub.detach(conn)


# --- Cursor de-dupe and updates ---------------------------------------------


async def test_static_cursor_skips_subsequent_broadcasts() -> None:
    """If the cursor doesn't change, no `update` messages should follow the
    initial `snapshot`."""
    hub = RealtimeHub(default_interval_ms=20)  # short tick to exercise loop
    hub.register_channel(StaticChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "static", None)
    await asyncio.sleep(0.15)  # several ticks have elapsed

    msgs = _drain(conn)
    # Exactly one ack + one snapshot, no updates.
    types = [m.type for m in msgs]  # type: ignore[attr-defined]
    assert types.count("snapshot") == 1
    assert types.count("update") == 0

    hub.detach(conn)


async def test_changing_cursor_emits_updates() -> None:
    hub = RealtimeHub(default_interval_ms=20)
    hub.register_channel(CounterChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "s1", "counter", None)
    await asyncio.sleep(0.12)  # several ticks

    msgs = _drain(conn)
    snapshots = [m for m in msgs if isinstance(m, SnapshotMessage)]
    updates = [m for m in msgs if isinstance(m, UpdateMessage)]
    assert len(snapshots) == 1
    assert len(updates) >= 1
    # Ticks are strictly increasing.
    seen = [snapshots[0].data["tick"], *(u.data["tick"] for u in updates)]
    assert seen == sorted(seen)
    assert seen[0] < seen[-1]

    hub.detach(conn)


# --- Connection bookkeeping -------------------------------------------------


async def test_detach_unsubscribes_all_and_cleans_pollers() -> None:
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(StaticChannel())
    hub.register_channel(ParamEchoChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "a", "static", None)
    hub.subscribe(conn, "b", "echo", {"id": "x"})
    hub.subscribe(conn, "c", "echo", {"id": "y"})
    assert hub.poller_count == 3

    hub.detach(conn)
    assert hub.poller_count == 0
    assert hub.connection_count == 0


async def test_max_subs_per_connection_enforced() -> None:
    hub = RealtimeHub(default_interval_ms=10_000, max_subs_per_conn=2)
    hub.register_channel(ParamEchoChannel())
    conn = _make_conn()
    hub.attach(conn)

    hub.subscribe(conn, "a", "echo", {"id": "1"})
    hub.subscribe(conn, "b", "echo", {"id": "2"})
    hub.subscribe(conn, "c", "echo", {"id": "3"})  # over the limit

    msgs = _drain(conn)
    types = [m.type for m in msgs]  # type: ignore[attr-defined]
    assert types.count("error") == 1
    error = next(m for m in msgs if m.type == "error")  # type: ignore[attr-defined]
    assert error.code == "too_many_subscriptions"  # type: ignore[attr-defined]

    hub.detach(conn)
