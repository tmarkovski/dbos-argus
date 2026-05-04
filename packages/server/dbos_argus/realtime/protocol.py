"""Wire protocol for the /ws endpoint.

One socket multiplexes many subscriptions, each tagged by a client-assigned
`sub_id`. Channel-specific payloads are opaque JSON and live in `data`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Client → server


class SubscribeMessage(BaseModel):
    type: Literal["subscribe"] = "subscribe"
    sub_id: str
    channel: str
    params: dict[str, Any] | None = None


class UnsubscribeMessage(BaseModel):
    type: Literal["unsubscribe"] = "unsubscribe"
    sub_id: str


class UpdateParamsMessage(BaseModel):
    """Re-key an existing subscription without re-rendering on the client.

    Server may swap the underlying poller (in `KeyedChannel`) but the
    `sub_id` is preserved. Client gets a fresh `snapshot` for the new params.
    """

    type: Literal["update_params"] = "update_params"
    sub_id: str
    params: dict[str, Any] | None = None


class PingMessage(BaseModel):
    type: Literal["ping"] = "ping"


ClientMessage = SubscribeMessage | UnsubscribeMessage | UpdateParamsMessage | PingMessage


# Server → client


class SnapshotMessage(BaseModel):
    """First payload after `subscribe` (or after `update_params`)."""

    type: Literal["snapshot"] = "snapshot"
    sub_id: str
    channel: str
    data: Any


class UpdateMessage(BaseModel):
    """Subsequent payload — sent only when the channel cursor advanced."""

    type: Literal["update"] = "update"
    sub_id: str
    channel: str
    data: Any


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    sub_id: str | None = None
    code: str
    message: str


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


class AckMessage(BaseModel):
    """Confirms that a non-data control message landed (subscribe / unsubscribe).

    Useful for tests and for clients that want to know when an unsubscribe
    has been honored on the server.
    """

    type: Literal["ack"] = "ack"
    sub_id: str
    op: Literal["subscribe", "unsubscribe", "update_params"]


ServerMessage = SnapshotMessage | UpdateMessage | ErrorMessage | PongMessage | AckMessage


# Convenience top-level discriminated unions for parsing.


class IncomingEnvelope(BaseModel):
    """Discriminator-only model for parsing arbitrary client messages.

    Pydantic doesn't dispatch a tagged union from a top-level `BaseModel`
    parse call without a wrapper. We use this purely to validate the
    `type` discriminator before routing — actual payload parsing happens
    against the concrete model in the union.
    """

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
