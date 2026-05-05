"""Realtime (WebSocket) layer.

Server-side pollers query DBOS system tables on a tick, gate on a cheap
cursor (e.g. `max(updated_at), count(*)`), and fan out snapshots to subscribed
clients over a single multiplexed `/ws` endpoint.

Architecture:
- `protocol`: Pydantic models for the wire format.
- `channel`: base `Channel` + `BroadcastChannel` (one shared poller per
  channel) and `KeyedChannel` (one poller per distinct params hash).
- `hub`: `RealtimeHub` tracks connections, subscriptions, and channel
  registry; routes incoming client messages.
- `endpoint`: FastAPI WebSocket route bound to a hub.

REST endpoints stay around for direct/curl access; the `/ws` layer is a
parallel push channel, not a replacement.
"""

from .channel import BroadcastChannel, Channel, KeyedChannel
from .endpoint import register_websocket_route
from .hub import RealtimeHub
from .protocol import ClientMessage, ServerMessage

__all__ = [
    "BroadcastChannel",
    "Channel",
    "ClientMessage",
    "KeyedChannel",
    "RealtimeHub",
    "ServerMessage",
    "register_websocket_route",
]
