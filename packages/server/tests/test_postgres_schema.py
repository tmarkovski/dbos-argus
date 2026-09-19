"""The Postgres adapter must qualify every table with the configured DBOS
system schema. These checks need no database: `create_async_engine` is lazy, so
constructing the adapter only renders its SQL.

The integration suite proves the same thing end to end when CI points it at a
non-default schema; this file keeps the guarantee on the offline `sqlite` leg
and on a plain local `uv run pytest`.
"""

from __future__ import annotations

import inspect
import re

import pytest
from dbos_argus.db import postgres
from dbos_argus.db.postgres import PostgresArgusDB, _build_workflow_sql
from dbos_argus.db.rows import WorkflowFilters
from dbos_argus.settings import Settings

_URL = "postgresql+asyncpg://u:p@localhost:5432/db"

# A table reference that isn't qualified with the custom schema below.
_DBOS_TABLES = (
    "workflow_status",
    "operation_outputs",
    "workflow_events",
    "workflow_events_history",
    "workflow_schedules",
    "notifications",
    "queues",
    "dbos_migrations",
)
_UNQUALIFIED = re.compile(
    r"\b(?:FROM|JOIN)\s+(?!\"custom_schema\"\.)(?:\w+\.)?(" + "|".join(_DBOS_TABLES) + r")\b"
)


def _adapter(schema: str = "custom_schema") -> PostgresArgusDB:
    return PostgresArgusDB(Settings(database_url=_URL, dbos_system_schema=schema))


def _rendered_sql(db: PostgresArgusDB) -> dict[str, str]:
    return {k: v for k, v in vars(db).items() if k.endswith("_sql")}


def test_every_sql_template_is_rendered_by_the_adapter() -> None:
    # A new `_FOO_SQL` template that `__init__` forgets to render would be
    # executed with a literal `{schema}` in it.
    templates = {n for n, v in vars(postgres).items() if n.endswith("_SQL") and isinstance(v, str)}
    templates -= {"ACTIVE_STATUSES_SQL", "ERROR_STATUSES_SQL"}
    rendered = set(_rendered_sql(_adapter()))
    assert {t.lower() for t in templates} == rendered


def test_rendered_templates_use_the_configured_schema() -> None:
    for name, sql in _rendered_sql(_adapter()).items():
        assert '"custom_schema".' in sql, name
        assert "{schema}" not in sql, name
        assert not _UNQUALIFIED.search(sql), f"{name}: {_UNQUALIFIED.search(sql)}"


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("q", [None, "dispatch"])
def test_workflow_list_sql_uses_the_configured_schema(grouped: bool, q: str | None) -> None:
    filters = WorkflowFilters(grouped=grouped, q=q, limit=10)
    sql, _ = _build_workflow_sql('"custom_schema"', grouped, filters)
    assert '"custom_schema".workflow_status' in sql
    assert not _UNQUALIFIED.search(sql)


def test_default_schema_renders_the_same_tables_as_before() -> None:
    sql = _rendered_sql(_adapter("dbos"))["_workflow_result_sql"]
    assert 'FROM "dbos".workflow_status' in sql


def test_adapter_source_has_no_hardcoded_dbos_prefix() -> None:
    # Covers the SQL built inline inside methods (cursors, throughput,
    # notifications), which the template checks above can't see.
    source = inspect.getsource(postgres)
    offenders = [
        line.strip() for line in source.splitlines() if re.search(r"\b(?:FROM|JOIN)\s+dbos\.", line)
    ]
    assert offenders == []
