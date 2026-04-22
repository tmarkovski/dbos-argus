"""WebSocket protocol — single source of truth for Argus <-> DBOS app messages.

The TypeScript mirror lives at packages/client-ts/src/protocol.ts and is generated
from the Pydantic models below via `pnpm run gen:protocol`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class HelloMessage(BaseModel):
    """Initial greeting sent from Argus server to a newly connected app."""

    type: Literal["hello"] = "hello"
    server_version: str
    connection_id: str
    received_at: datetime


class AppConnectMessage(BaseModel):
    """Sent by a DBOS app on the /ws/apps channel to identify itself."""

    type: Literal["app.connect"] = "app.connect"
    app_name: str
    sdk: Literal["python", "typescript"]
    sdk_version: str


def _now_utc() -> datetime:
    return datetime.now(UTC)


class PingMessage(BaseModel):
    type: Literal["ping"] = "ping"
    ts: datetime = Field(default_factory=_now_utc)


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"
    ts: datetime = Field(default_factory=_now_utc)


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


# Union types for use by generators and future routers.
ServerMessage = HelloMessage | PongMessage | ErrorMessage
ClientMessage = AppConnectMessage | PingMessage

__all__ = [
    "AppConnectMessage",
    "ClientMessage",
    "ErrorMessage",
    "HelloMessage",
    "PingMessage",
    "PongMessage",
    "ServerMessage",
]
