import logging
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .protocol import HelloMessage
from .settings import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("dbos_argus")

app = FastAPI(
    title="dbos-argus",
    version=__version__,
    description="Self-hosted management console for DBOS Transact.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@app.websocket("/ws/apps")
async def ws_apps(ws: WebSocket, api_key: str | None = Query(default=None)) -> None:
    # TODO(auth): verify api_key against apps.api_key_hash and bind connection to app_id.
    await ws.accept()
    connection_id = str(uuid.uuid4())
    key_preview = (api_key[:4] + "…") if api_key else "<none>"
    logger.info("ws/apps connected conn=%s api_key=%s", connection_id, key_preview)

    hello = HelloMessage(
        server_version=__version__,
        connection_id=connection_id,
        received_at=datetime.now(UTC),
    )
    await ws.send_json(hello.model_dump(mode="json"))

    try:
        while True:
            msg = await ws.receive_text()
            logger.debug("ws/apps recv conn=%s msg=%s", connection_id, msg)
            await ws.send_text(msg)
    except WebSocketDisconnect:
        logger.info("ws/apps disconnected conn=%s", connection_id)
