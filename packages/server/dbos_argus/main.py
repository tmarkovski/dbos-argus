import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from . import __version__
from .db import engine
from .decoding import decode_dbos_value
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


class WorkflowStep(BaseModel):
    # Which workflow in the family this step belongs to.
    workflow_id: str
    function_id: int
    function_name: str
    output: str | None
    error: str | None
    child_workflow_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    # Serialization format of `output` / `error`. DBOS stores "pickle" by
    # default (base64-encoded pickle bytes); apps can opt into "json".
    serialization: str | None
    # Best-effort pretty-printed JSON of the decoded output/error. None when
    # the payload wasn't decodable — e.g. pickled custom classes which our
    # restricted unpickler refuses to instantiate. See decoding.py.
    output_decoded: str | None
    error_decoded: str | None
    # For `DBOS.setEvent` rows, the event key — joined from
    # `dbos.workflow_events_history` on `(workflow_uuid, function_id)`. Always
    # null for `DBOS.getEvent` because DBOS doesn't persist the call's input
    # args (target workflow id + key) anywhere queryable, and we refuse to
    # guess. The getEvent's deserialized value is in `output_decoded`.
    event_key: str | None


# Richer version of WorkflowListItem used by the detail endpoint — includes
# output/error so clients can display workflow results. Kept separate from
# WorkflowListItem to avoid sending potentially-large output payloads on the
# workflows-list endpoint.
class WorkflowFamilyItem(WorkflowListItem):
    output: str | None
    error: str | None
    serialization: str | None
    output_decoded: str | None
    error_decoded: str | None


class WorkflowDetail(BaseModel):
    workflow_id: str
    parent_workflow_id: str | None
    name: str | None
    status: str | None
    started_at: datetime
    updated_at: datetime
    # Entire workflow family rooted at the topmost ancestor, in DFS order
    # (same shape & ordering as the grouped list endpoint). Single-entry
    # when the workflow has no parent and no children.
    family: list[WorkflowFamilyItem]
    # Steps (dbos.operation_outputs rows) for every workflow in `family`,
    # ordered by (workflow_id, function_id ASC). Clients group by
    # workflow_id to build per-workflow timelines.
    steps: list[WorkflowStep]


# Walks up parent_workflow_id to find the topmost ancestor (or the workflow
# itself if it has no parent), then expands that ancestor's whole subtree in
# DFS order — matching how the list endpoint groups trees.
@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> WorkflowDetail:
    sql = """
        WITH RECURSIVE
            up AS (
                SELECT workflow_uuid, parent_workflow_id, 0 AS lvl
                FROM dbos.workflow_status
                WHERE workflow_uuid = :workflow_id

                UNION ALL

                SELECT ws.workflow_uuid, ws.parent_workflow_id, u.lvl + 1
                FROM dbos.workflow_status ws
                JOIN up u ON ws.workflow_uuid = u.parent_workflow_id
            ),
            root AS (
                SELECT workflow_uuid
                FROM up
                ORDER BY lvl DESC
                LIMIT 1
            ),
            tree AS (
                SELECT
                    ws.workflow_uuid,
                    ws.parent_workflow_id,
                    ws.name,
                    ws.status,
                    ws.output,
                    ws.error,
                    ws.serialization,
                    COALESCE(ws.started_at_epoch_ms, ws.created_at) AS started_ms,
                    ws.updated_at AS updated_ms,
                    0 AS depth,
                    ARRAY[COALESCE(ws.started_at_epoch_ms, ws.created_at)] AS sort_path
                FROM dbos.workflow_status ws
                JOIN root r ON ws.workflow_uuid = r.workflow_uuid

                UNION ALL

                SELECT
                    c.workflow_uuid,
                    c.parent_workflow_id,
                    c.name,
                    c.status,
                    c.output,
                    c.error,
                    c.serialization,
                    COALESCE(c.started_at_epoch_ms, c.created_at),
                    c.updated_at,
                    t.depth + 1,
                    t.sort_path || COALESCE(c.started_at_epoch_ms, c.created_at)
                FROM dbos.workflow_status c
                JOIN tree t ON c.parent_workflow_id = t.workflow_uuid
            )
        SELECT
            workflow_uuid, parent_workflow_id, name, status, output, error,
            serialization, started_ms, updated_ms, depth
        FROM tree
        ORDER BY sort_path ASC
    """
    steps_sql = """
        SELECT
            o.workflow_uuid,
            o.function_id,
            o.function_name,
            o.output,
            o.error,
            o.child_workflow_id,
            o.started_at_epoch_ms,
            o.completed_at_epoch_ms,
            o.serialization,
            seh.key AS event_key
        FROM dbos.operation_outputs o
        LEFT JOIN dbos.workflow_events_history seh
            ON o.function_name = 'DBOS.setEvent'
            AND seh.workflow_uuid = o.workflow_uuid
            AND seh.function_id = o.function_id
        WHERE o.workflow_uuid = ANY(:workflow_ids)
        ORDER BY o.workflow_uuid, o.function_id ASC
    """

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), {"workflow_id": workflow_id})
            rows = result.fetchall()
            family_ids = [r.workflow_uuid for r in rows]
            steps_result = await conn.execute(text(steps_sql), {"workflow_ids": family_ids})
            step_rows = steps_result.fetchall()
    except ProgrammingError as e:
        raise HTTPException(status_code=404, detail="workflow not found") from e

    if not rows:
        raise HTTPException(status_code=404, detail="workflow not found")

    family = [
        WorkflowFamilyItem(
            workflow_id=r.workflow_uuid,
            parent_workflow_id=r.parent_workflow_id,
            name=r.name,
            status=r.status,
            output=r.output,
            error=r.error,
            serialization=r.serialization,
            output_decoded=decode_dbos_value(r.output, r.serialization),
            error_decoded=decode_dbos_value(r.error, r.serialization),
            started_at=datetime.fromtimestamp(r.started_ms / 1000, tz=UTC),
            updated_at=datetime.fromtimestamp(r.updated_ms / 1000, tz=UTC),
            depth=r.depth,
        )
        for r in rows
    ]
    steps = [
        WorkflowStep(
            workflow_id=s.workflow_uuid,
            function_id=s.function_id,
            function_name=s.function_name,
            output=s.output,
            error=s.error,
            serialization=s.serialization,
            output_decoded=decode_dbos_value(s.output, s.serialization),
            error_decoded=decode_dbos_value(s.error, s.serialization),
            child_workflow_id=s.child_workflow_id,
            started_at=(
                datetime.fromtimestamp(s.started_at_epoch_ms / 1000, tz=UTC)
                if s.started_at_epoch_ms is not None
                else None
            ),
            completed_at=(
                datetime.fromtimestamp(s.completed_at_epoch_ms / 1000, tz=UTC)
                if s.completed_at_epoch_ms is not None
                else None
            ),
            event_key=s.event_key,
        )
        for s in step_rows
    ]
    self_item = next(w for w in family if w.workflow_id == workflow_id)
    return WorkflowDetail(
        workflow_id=self_item.workflow_id,
        parent_workflow_id=self_item.parent_workflow_id,
        name=self_item.name,
        status=self_item.status,
        started_at=self_item.started_at,
        updated_at=self_item.updated_at,
        family=family,
        steps=steps,
    )


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
