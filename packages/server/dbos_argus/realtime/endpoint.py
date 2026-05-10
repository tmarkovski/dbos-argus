"""FastAPI WebSocket route bound to a `RealtimeHub`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .hub import Connection, RealtimeHub
from .protocol import (
    ErrorMessage,
    PongMessage,
    ServerMessage,
)

logger = logging.getLogger("dbos_argus.realtime")


def _origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """Strict origin check.

    `allowed` comes from `cors_origins_list`. An empty list (or a "*" entry)
    permits any origin — same trust model as the REST CORS middleware.
    Missing Origin header is allowed because non-browser clients (curl,
    test runners, MCP) don't send one.
    """
    if not allowed or "*" in allowed:
        return True
    if origin is None:
        return True
    return origin in allowed


def register_websocket_route(
    app: FastAPI, hub: RealtimeHub, *, path: str = "/ws", allowed_origins: list[str] | None = None
) -> None:
    allowed = list(allowed_origins or [])

    @app.websocket(path)
    async def ws_endpoint(websocket: WebSocket) -> None:  # pragma: no cover - thin glue
        origin = websocket.headers.get("origin")
        if not _origin_allowed(origin, allowed):
            await websocket.close(code=1008, reason="origin not allowed")
            return

        await websocket.accept()
        conn = Connection(websocket=websocket)
        hub.attach(conn)
        writer = asyncio.create_task(_writer(conn), name="ws:writer")

        try:
            while True:
                msg = await websocket.receive_json()
                await _handle_client_message(hub, conn, msg)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("realtime: ws receive error: %s", e)
        finally:
            hub.detach(conn)
            writer.cancel()
            try:
                await writer
            except asyncio.CancelledError:
                pass


async def _writer(conn: Connection) -> None:
    """Drain the connection's outbound queue to the websocket.

    Runs as its own task so a slow client can't block hub broadcasts.
    """
    try:
        while True:
            msg: ServerMessage = await conn.out_queue.get()
            await conn.websocket.send_json(msg.model_dump())
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("realtime: ws writer error: %s", e)
        # Mark closed and force the socket shut so the receive loop
        # unblocks and `hub.detach` runs — otherwise the reader keeps
        # awaiting frames the peer is no longer reading.
        conn.closed = True
        try:
            await conn.websocket.close(code=1011, reason="writer error")
        except Exception:
            pass


async def _handle_client_message(hub: RealtimeHub, conn: Connection, msg: Any) -> None:
    if not isinstance(msg, dict):
        conn.enqueue(ErrorMessage(code="bad_message", message="expected JSON object"))
        return
    msg_type = msg.get("type")

    if msg_type == "ping":
        conn.enqueue(PongMessage())
        return

    if msg_type == "subscribe":
        sub_id = msg.get("sub_id")
        channel = msg.get("channel")
        params = msg.get("params")
        if not isinstance(sub_id, str) or not isinstance(channel, str):
            conn.enqueue(
                ErrorMessage(code="bad_message", message="subscribe requires sub_id + channel")
            )
            return
        hub.subscribe(conn, sub_id, channel, params if isinstance(params, dict) else None)
        return

    if msg_type == "unsubscribe":
        sub_id = msg.get("sub_id")
        if not isinstance(sub_id, str):
            conn.enqueue(ErrorMessage(code="bad_message", message="unsubscribe requires sub_id"))
            return
        hub.unsubscribe(conn, sub_id)
        return

    if msg_type == "update_params":
        sub_id = msg.get("sub_id")
        params = msg.get("params")
        if not isinstance(sub_id, str):
            conn.enqueue(ErrorMessage(code="bad_message", message="update_params requires sub_id"))
            return
        hub.update_params(conn, sub_id, params if isinstance(params, dict) else None)
        return

    conn.enqueue(ErrorMessage(code="unknown_type", message=f"unknown message type: {msg_type!r}"))
