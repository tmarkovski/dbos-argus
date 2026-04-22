import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from . import __version__
from .db import engine
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
    db_up = True
    db_error: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        db_up = False
        db_error = str(e)
    body: dict[str, str] = {
        "status": "ok" if db_up else "degraded",
        "database": "up" if db_up else "down",
        "database_url": engine.url.render_as_string(hide_password=True),
    }
    if db_error is not None:
        body["database_error"] = db_error
    return body


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


CONSOLE_DIR = Path(os.environ.get("ARGUS_CONSOLE_DIR", "/app/console"))

if CONSOLE_DIR.is_dir() and (CONSOLE_DIR / "index.html").is_file():
    logger.info("serving console from %s", CONSOLE_DIR)

    @app.get("/{full_path:path}")
    async def console_spa(request: Request, full_path: str) -> FileResponse:
        candidate = (CONSOLE_DIR / full_path).resolve()
        try:
            candidate.relative_to(CONSOLE_DIR.resolve())
        except ValueError as e:
            raise HTTPException(status_code=404) from e
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(CONSOLE_DIR / "index.html")
else:
    logger.info("console static dir not found at %s; skipping SPA mount", CONSOLE_DIR)
