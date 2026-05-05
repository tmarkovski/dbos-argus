"""Adapter interface for the DBOS system database.

Argus reads — never writes — DBOS Transact's system tables. Different DBOS
backends use different SQL dialects (currently Postgres; SQLite coming), so
endpoints in `main.py` go through this protocol rather than emitting SQL
directly. Each implementation owns its engine and its own queries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine

from ..schema_dump import SchemaDump
from .rows import (
    NotificationFilters,
    NotificationsRows,
    ResultRow,
    ScheduleRow,
    StatsRow,
    ThroughputRow,
    WorkflowDetailRows,
    WorkflowFilters,
    WorkflowListRow,
)


class ArgusDB(ABC):
    """Per-dialect adapter. Read-only — no method ever writes."""

    engine: AsyncEngine

    @property
    @abstractmethod
    def display_url(self) -> str:
        """Connection URL with credentials redacted, for `/healthz`."""

    @abstractmethod
    async def healthcheck(self) -> None:
        """Run a no-op query; raise on failure."""

    @abstractmethod
    async def reflect_schema(self, schema: str = "dbos") -> SchemaDump:
        """Return the live DB's schema as a dialect-neutral `SchemaDump`."""

    @abstractmethod
    async def list_workflows(self, filters: WorkflowFilters) -> list[WorkflowListRow]:
        """Workflow list page rows, with op counts. Empty when the DBOS
        schema doesn't exist yet."""

    @abstractmethod
    async def get_workflow_detail(self, workflow_id: str) -> WorkflowDetailRows:
        """Whole family tree + steps + events for a single workflow's family.
        Empty when not found / schema absent — `main.py` raises 404."""

    @abstractmethod
    async def get_workflow_result(self, workflow_id: str) -> ResultRow | None:
        """Lazy-loaded output/error payload for one workflow row."""

    @abstractmethod
    async def get_step_result(self, workflow_id: str, function_id: int) -> ResultRow | None:
        """Lazy-loaded output/error payload for one operation_outputs row."""

    @abstractmethod
    async def get_stats(self, since_ms: int) -> StatsRow:
        """Dashboard rollup. Returns a zeroed `StatsRow` when schema absent."""

    @abstractmethod
    async def get_throughput(
        self, since_ms: int, until_ms: int, bucket: Literal["hour", "day"]
    ) -> list[ThroughputRow]:
        """Time-bucketed succeeded/errored/running counts."""

    @abstractmethod
    async def list_schedules(self) -> list[ScheduleRow]: ...

    @abstractmethod
    async def list_notifications(self, filters: NotificationFilters) -> NotificationsRows:
        """Notifications + per-destination ancestor chains, fetched together."""

    # Cursors are cheap "did anything change?" probes used by the realtime
    # layer's pollers — they gate the heavier snapshot query behind a cursor
    # change. Each returns a comparable tuple. ("empty",) when the dbos.*
    # schema isn't there yet (preserves the pre-connect empty state without
    # raising). Must be orders of magnitude cheaper than the snapshot.

    @abstractmethod
    async def workflows_cursor(self) -> tuple:
        """Coarse global probe over workflow_status + operation_outputs."""

    @abstractmethod
    async def stats_cursor(self) -> tuple:
        """Probe for the dashboard rollup."""

    @abstractmethod
    async def schedules_cursor(self) -> tuple:
        """Probe for the schedules list (advances on each cron tick)."""

    @abstractmethod
    async def notifications_cursor(self) -> tuple:
        """Probe over notifications (new rows or consumed-state flips)."""

    @abstractmethod
    async def timeseries_cursor(self) -> tuple:
        """Probe for the throughput chart (excluding the time-window tick)."""
