import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

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


class WorkflowListItem(BaseModel):
    workflow_id: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    started_at: datetime
    updated_at: datetime
    depth: int


# In grouped mode, filters apply to the `roots` CTE only — matching roots come
# along with their entire descendant tree. Each row's sort_path is the
# accumulated started_ms from root down to itself — Postgres array ordering
# then yields a DFS traversal with children sitting directly under their parent.
#
# In flat mode, filters apply to all workflows; no recursion, ordered by
# started_at DESC.
def _build_workflow_sql(grouped: bool, filters: dict[str, object]) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {"limit": filters["limit"]}
    conditions: list[str] = []

    if filters.get("workflow_id"):
        conditions.append("workflow_uuid ILIKE :workflow_id_pat")
        params["workflow_id_pat"] = f"%{filters['workflow_id']}%"
    if filters.get("name"):
        conditions.append("name ILIKE :name_pat")
        params["name_pat"] = f"%{filters['name']}%"
    if filters.get("started_after") is not None:
        conditions.append("COALESCE(started_at_epoch_ms, created_at) >= :started_after_ms")
        params["started_after_ms"] = filters["started_after"]
    if filters.get("started_before") is not None:
        conditions.append("COALESCE(started_at_epoch_ms, created_at) <= :started_before_ms")
        params["started_before_ms"] = filters["started_before"]
    if filters.get("statuses"):
        conditions.append("status = ANY(:statuses)")
        params["statuses"] = filters["statuses"]

    where_extra = (" AND " + " AND ".join(conditions)) if conditions else ""

    if grouped:
        sql = f"""
            WITH RECURSIVE
                roots AS (
                    SELECT workflow_uuid, updated_at
                    FROM dbos.workflow_status
                    WHERE parent_workflow_id IS NULL{where_extra}
                    ORDER BY updated_at DESC
                    LIMIT :limit
                ),
                tree AS (
                    SELECT
                        ws.workflow_uuid,
                        ws.parent_workflow_id,
                        ws.name,
                        ws.status,
                        COALESCE(ws.started_at_epoch_ms, ws.created_at) AS started_ms,
                        ws.updated_at AS updated_ms,
                        0 AS depth,
                        r.updated_at AS root_updated_at,
                        ARRAY[COALESCE(ws.started_at_epoch_ms, ws.created_at)] AS sort_path
                    FROM dbos.workflow_status ws
                    JOIN roots r ON ws.workflow_uuid = r.workflow_uuid

                    UNION ALL

                    SELECT
                        c.workflow_uuid,
                        c.parent_workflow_id,
                        c.name,
                        c.status,
                        COALESCE(c.started_at_epoch_ms, c.created_at),
                        c.updated_at,
                        t.depth + 1,
                        t.root_updated_at,
                        t.sort_path || COALESCE(c.started_at_epoch_ms, c.created_at)
                    FROM dbos.workflow_status c
                    JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
                )
            SELECT workflow_uuid, parent_workflow_id, name, status, started_ms, updated_ms, depth
            FROM tree
            ORDER BY root_updated_at DESC, sort_path ASC
        """
    else:
        flat_where = f"WHERE 1=1{where_extra}" if where_extra else ""
        sql = f"""
            SELECT
                workflow_uuid,
                parent_workflow_id,
                name,
                status,
                COALESCE(started_at_epoch_ms, created_at) AS started_ms,
                updated_at AS updated_ms,
                0 AS depth
            FROM dbos.workflow_status
            {flat_where}
            ORDER BY COALESCE(started_at_epoch_ms, created_at) DESC
            LIMIT :limit
        """
    return sql, params


@app.get("/api/workflows")
async def list_workflows(
    limit: int = Query(default=50, ge=1, le=200),
    workflow_id: str | None = None,
    name: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    grouped: bool = True,
) -> list[WorkflowListItem]:
    filters: dict[str, object] = {
        "limit": limit,
        "workflow_id": workflow_id,
        "name": name,
        "started_after": int(started_after.timestamp() * 1000) if started_after else None,
        "started_before": int(started_before.timestamp() * 1000) if started_before else None,
        "statuses": status if status else None,
    }
    sql, params = _build_workflow_sql(grouped, filters)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = result.fetchall()
    except ProgrammingError:
        # dbos schema hasn't been created yet — no app has connected.
        return []
    return [
        WorkflowListItem(
            workflow_id=r.workflow_uuid,
            parent_workflow_id=r.parent_workflow_id,
            name=r.name,
            status=r.status,
            started_at=datetime.fromtimestamp(r.started_ms / 1000, tz=UTC),
            updated_at=datetime.fromtimestamp(r.updated_ms / 1000, tz=UTC),
            depth=r.depth,
        )
        for r in rows
    ]


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
