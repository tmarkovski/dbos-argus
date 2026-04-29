"""Generic schema-dump shape and live-DB extraction.

A `SchemaDump` is just a flat description of `(schema_name, tables[], columns[])`
queried from `information_schema`. The same shape is produced both for the
expected dump (loaded from the JSON snapshot shipped with the package) and the
actual dump (queried from the running DB), so `schema_diff.diff_schemas` can
compare them without any DBOS-specific knowledge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]


@dataclass(frozen=True)
class SchemaDump:
    schema: str
    tables: tuple[TableInfo, ...]

    def table_index(self) -> dict[str, TableInfo]:
        return {t.name: t for t in self.tables}


def to_json(dump: SchemaDump) -> dict[str, Any]:
    return {
        "schema": dump.schema,
        "tables": [
            {
                "name": t.name,
                "columns": [{"name": c.name, "data_type": c.data_type} for c in t.columns],
            }
            for t in dump.tables
        ],
    }


def from_json(payload: dict[str, Any]) -> SchemaDump:
    return SchemaDump(
        schema=payload["schema"],
        tables=tuple(
            TableInfo(
                name=t["name"],
                columns=tuple(
                    ColumnInfo(name=c["name"], data_type=c["data_type"]) for c in t["columns"]
                ),
            )
            for t in payload["tables"]
        ),
    )


_TABLES_SQL = text(
    """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = :schema
    """
)

_COLUMNS_SQL = text(
    """
    SELECT table_name, column_name, data_type, ordinal_position
    FROM information_schema.columns
    WHERE table_schema = :schema
    ORDER BY table_name, ordinal_position
    """
)


async def dump_live_schema(conn: AsyncConnection, schema: str = "dbos") -> SchemaDump:
    """Reflect the live DB into a `SchemaDump` rooted at `schema`."""
    table_rows = (await conn.execute(_TABLES_SQL, {"schema": schema})).fetchall()
    column_rows = (await conn.execute(_COLUMNS_SQL, {"schema": schema})).fetchall()

    columns_by_table: dict[str, list[ColumnInfo]] = {}
    for r in column_rows:
        columns_by_table.setdefault(r.table_name, []).append(
            ColumnInfo(name=r.column_name, data_type=r.data_type)
        )

    tables = tuple(
        TableInfo(name=row.table_name, columns=tuple(columns_by_table.get(row.table_name, [])))
        for row in sorted(table_rows, key=lambda r: r.table_name)
    )
    return SchemaDump(schema=schema, tables=tables)


def load_expected_dump() -> SchemaDump:
    """Load the snapshot of the schema Argus expects from `data/expected_schema.json`."""
    payload = json.loads(files("dbos_argus.data").joinpath("expected_schema.json").read_text())
    return from_json(payload)
