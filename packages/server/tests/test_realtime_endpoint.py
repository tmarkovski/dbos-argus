"""End-to-end WebSocket tests using FastAPI's TestClient.

Validates the wire protocol: ack-then-snapshot ordering, ping/pong, error
shapes, multiplexed sub_ids on a single socket. Uses fake channels swapped
into a fresh app — avoids depending on the real DB, which we don't want
test-runs to require.
"""

from __future__ import annotations

from typing import Any

from dbos_argus.realtime import RealtimeHub, register_websocket_route
from dbos_argus.realtime.channel import BroadcastChannel, KeyedChannel
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Static(BroadcastChannel):
    name = "static"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return "v1"

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        return {"value": "static"}


class _Echo(KeyedChannel):
    name = "echo"

    async def cursor(self, params: dict[str, Any] | None) -> Any:
        return ("v", self.params_key(params))

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        return {"params": params or {}}


def _make_app() -> FastAPI:
    app = FastAPI()
    hub = RealtimeHub(default_interval_ms=10_000)
    hub.register_channel(_Static())
    hub.register_channel(_Echo())
    # Allow any origin for tests (TestClient doesn't send Origin).
    register_websocket_route(app, hub, allowed_origins=[])
    return app


def _drain_until(ws, predicate, *, max_msgs: int = 8) -> list[dict[str, Any]]:
    """Read messages until `predicate(msg)` returns True or we hit max_msgs.

    Returns every message read, including the one that satisfied the
    predicate. Raises RuntimeError on overflow.
    """
    out: list[dict[str, Any]] = []
    for _ in range(max_msgs):
        msg = ws.receive_json()
        out.append(msg)
        if predicate(msg):
            return out
    raise RuntimeError(f"predicate not satisfied within {max_msgs} messages: {out}")


def test_subscribe_emits_ack_then_snapshot() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "sub_id": "s1", "channel": "static"})
        msgs = _drain_until(ws, lambda m: m["type"] == "snapshot")
        assert msgs[0] == {"type": "ack", "sub_id": "s1", "op": "subscribe"}
        snap = msgs[-1]
        assert snap["sub_id"] == "s1"
        assert snap["channel"] == "static"
        assert snap["data"] == {"value": "static"}


def test_ping_pong() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        assert msg == {"type": "pong"}


def test_unknown_channel_returns_error() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "sub_id": "s1", "channel": "nope"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["sub_id"] == "s1"
        assert msg["code"] == "unknown_channel"


def test_unsubscribe_acks_and_silences_channel() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "sub_id": "s1", "channel": "static"})
        _drain_until(ws, lambda m: m["type"] == "snapshot")

        ws.send_json({"type": "unsubscribe", "sub_id": "s1"})
        ack = ws.receive_json()
        assert ack == {"type": "ack", "sub_id": "s1", "op": "unsubscribe"}


def test_multiple_subscriptions_share_one_socket() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "sub_id": "a", "channel": "echo", "params": {"id": "x"}})
        ws.send_json({"type": "subscribe", "sub_id": "b", "channel": "echo", "params": {"id": "y"}})

        # Each sub gets its own ack + snapshot. The hub doesn't guarantee
        # ordering across subs, but every message tags its sub_id, so we
        # can sort them out by that.
        seen_acks: set[str] = set()
        seen_snaps: dict[str, dict[str, Any]] = {}
        for _ in range(4):
            msg = ws.receive_json()
            if msg["type"] == "ack":
                seen_acks.add(msg["sub_id"])
            elif msg["type"] == "snapshot":
                seen_snaps[msg["sub_id"]] = msg["data"]
        assert seen_acks == {"a", "b"}
        assert seen_snaps["a"] == {"params": {"id": "x"}}
        assert seen_snaps["b"] == {"params": {"id": "y"}}


def test_update_params_emits_fresh_snapshot() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "subscribe", "sub_id": "s1", "channel": "echo", "params": {"id": "x"}}
        )
        _drain_until(ws, lambda m: m["type"] == "snapshot")

        ws.send_json({"type": "update_params", "sub_id": "s1", "params": {"id": "y"}})
        msgs = _drain_until(ws, lambda m: m["type"] == "snapshot")
        # ack + snapshot for the new params.
        types = [m["type"] for m in msgs]
        assert "ack" in types
        snap = msgs[-1]
        assert snap["data"] == {"params": {"id": "y"}}


def test_bad_message_returns_error() -> None:
    with TestClient(_make_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "frobnicate"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "unknown_type"
