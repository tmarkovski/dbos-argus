from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_STRING_TYPES = ("text", "character varying", "character")
_TIMESTAMP_TYPES = (
    "text",
    "character varying",
    "timestamp without time zone",
    "timestamp with time zone",
)


@dataclass(frozen=True)
class ColumnExpectation:
    name: str
    accepted_data_types: tuple[str, ...]

    @property
    def expected_type_label(self) -> str:
        return " or ".join(self.accepted_data_types)


@dataclass(frozen=True)
class TableExpectation:
    name: str
    columns: tuple[ColumnExpectation, ...]


@dataclass(frozen=True)
class SchemaIssue:
    kind: Literal["missing_table", "missing_column", "wrong_type"]
    table_name: str
    column_name: str | None
    expected_type: str | None
    actual_type: str | None
    detail: str


DBOS_SCHEMA_EXPECTATIONS: tuple[TableExpectation, ...] = (
    TableExpectation(
        name="workflow_status",
        columns=(
            ColumnExpectation("workflow_uuid", _STRING_TYPES),
            ColumnExpectation("parent_workflow_id", _STRING_TYPES),
            ColumnExpectation("name", _STRING_TYPES),
            ColumnExpectation("status", _STRING_TYPES),
            ColumnExpectation("queue_name", _STRING_TYPES),
            ColumnExpectation("executor_id", _STRING_TYPES),
            ColumnExpectation("started_at_epoch_ms", ("bigint",)),
            ColumnExpectation("created_at", ("bigint",)),
            ColumnExpectation("updated_at", ("bigint",)),
            ColumnExpectation("output", _STRING_TYPES),
            ColumnExpectation("error", _STRING_TYPES),
            ColumnExpectation("serialization", _STRING_TYPES),
        ),
    ),
    TableExpectation(
        name="operation_outputs",
        columns=(
            ColumnExpectation("workflow_uuid", _STRING_TYPES),
            ColumnExpectation("function_id", ("integer",)),
            ColumnExpectation("function_name", _STRING_TYPES),
            ColumnExpectation("output", _STRING_TYPES),
            ColumnExpectation("error", _STRING_TYPES),
            ColumnExpectation("child_workflow_id", _STRING_TYPES),
            ColumnExpectation("started_at_epoch_ms", ("bigint",)),
            ColumnExpectation("completed_at_epoch_ms", ("bigint",)),
            ColumnExpectation("serialization", _STRING_TYPES),
        ),
    ),
    TableExpectation(
        name="workflow_events_history",
        columns=(
            ColumnExpectation("workflow_uuid", _STRING_TYPES),
            ColumnExpectation("function_id", ("integer",)),
            ColumnExpectation("key", _STRING_TYPES),
        ),
    ),
    TableExpectation(
        name="notifications",
        columns=(
            ColumnExpectation("message_uuid", _STRING_TYPES),
            ColumnExpectation("destination_uuid", _STRING_TYPES),
            ColumnExpectation("topic", _STRING_TYPES),
            ColumnExpectation("consumed", ("boolean",)),
            ColumnExpectation("created_at_epoch_ms", ("bigint",)),
            ColumnExpectation("message", _STRING_TYPES),
            ColumnExpectation("serialization", _STRING_TYPES),
        ),
    ),
    TableExpectation(
        name="workflow_schedules",
        columns=(
            ColumnExpectation("schedule_id", _STRING_TYPES),
            ColumnExpectation("schedule_name", _STRING_TYPES),
            ColumnExpectation("workflow_name", _STRING_TYPES),
            ColumnExpectation("workflow_class_name", _STRING_TYPES),
            ColumnExpectation("schedule", _STRING_TYPES),
            ColumnExpectation("status", _STRING_TYPES),
            ColumnExpectation("last_fired_at", _TIMESTAMP_TYPES),
            ColumnExpectation("automatic_backfill", ("boolean",)),
            ColumnExpectation("cron_timezone", _STRING_TYPES),
            ColumnExpectation("queue_name", _STRING_TYPES),
        ),
    ),
)

_EXPECTED_TABLES = {table.name for table in DBOS_SCHEMA_EXPECTATIONS}

_TABLES_SQL = text(
    """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'dbos'
    """
)

_COLUMNS_SQL = text(
    """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'dbos'
    """
)


def collect_schema_issues(
    existing_tables: set[str],
    existing_columns: dict[tuple[str, str], str],
) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []

    for table in DBOS_SCHEMA_EXPECTATIONS:
        if table.name not in existing_tables:
            issues.append(
                SchemaIssue(
                    kind="missing_table",
                    table_name=table.name,
                    column_name=None,
                    expected_type=None,
                    actual_type=None,
                    detail=f"Missing required table dbos.{table.name}.",
                )
            )
            continue

        for column in table.columns:
            actual_type = existing_columns.get((table.name, column.name))
            if actual_type is None:
                issues.append(
                    SchemaIssue(
                        kind="missing_column",
                        table_name=table.name,
                        column_name=column.name,
                        expected_type=column.expected_type_label,
                        actual_type=None,
                        detail=f"Missing required column dbos.{table.name}.{column.name}.",
                    )
                )
                continue

            if actual_type not in column.accepted_data_types:
                issues.append(
                    SchemaIssue(
                        kind="wrong_type",
                        table_name=table.name,
                        column_name=column.name,
                        expected_type=column.expected_type_label,
                        actual_type=actual_type,
                        detail=(
                            f"Column dbos.{table.name}.{column.name} has type {actual_type}; "
                            f"expected {column.expected_type_label}."
                        ),
                    )
                )

    return issues


async def inspect_dbos_schema(conn: AsyncConnection) -> list[SchemaIssue]:
    table_rows = (await conn.execute(_TABLES_SQL)).fetchall()
    column_rows = (await conn.execute(_COLUMNS_SQL)).fetchall()

    existing_tables = {row.table_name for row in table_rows if row.table_name in _EXPECTED_TABLES}
    existing_columns = {
        (row.table_name, row.column_name): row.data_type
        for row in column_rows
        if row.table_name in _EXPECTED_TABLES
    }
    return collect_schema_issues(existing_tables, existing_columns)
