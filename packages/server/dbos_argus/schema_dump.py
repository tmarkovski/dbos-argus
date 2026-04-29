"""Generic schema-dump shape and live-DB extraction.

A `SchemaDump` is a structured description of `(schema_name, tables[], columns[])`.
Two producers feed the same shape:

- The packaged JSON snapshot at `data/dbos_schema.json` — the full DBOS Postgres
  schema as of a known DBOS version. Each column carries an `argus` boolean
  marking whether the Argus backend actually reads it.
- A live AsyncConnection reflected via `information_schema`.

Runtime diagnostics call `load_full_dump()` then `argus_only()` to narrow to
the columns Argus depends on, and diff against `dump_live_schema(...)` of the
target DB. The CI watchdog uses the unfiltered dump to track every change DBOS
ships, including columns we don't currently use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    # True iff the Argus backend reads this column. Only used in the packaged
    # snapshot — live dumps default to False since reflection has no concept
    # of "is Argus interested".
    argus: bool = False


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]


@dataclass(frozen=True)
class SchemaDump:
    schema: str
    tables: tuple[TableInfo, ...]
    meta: dict[str, Any] = field(default_factory=dict)

    def table_index(self) -> dict[str, TableInfo]:
        return {t.name: t for t in self.tables}


def to_json(dump: SchemaDump) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": dump.schema}
    if dump.meta:
        payload["meta"] = dict(dump.meta)
    payload["tables"] = [
        {
            "name": t.name,
            "columns": [
                {"name": c.name, "data_type": c.data_type, "argus": c.argus} for c in t.columns
            ],
        }
        for t in dump.tables
    ]
    return payload


def from_json(payload: dict[str, Any]) -> SchemaDump:
    return SchemaDump(
        schema=payload["schema"],
        meta=dict(payload.get("meta", {})),
        tables=tuple(
            TableInfo(
                name=t["name"],
                columns=tuple(
                    ColumnInfo(
                        name=c["name"],
                        data_type=c["data_type"],
                        argus=bool(c.get("argus", False)),
                    )
                    for c in t["columns"]
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


def load_full_dump(path: Path | None = None) -> SchemaDump:
    """Load the packaged DBOS schema snapshot (`data/dbos_schema.json`)."""
    if path is None:
        payload = json.loads(files("dbos_argus.data").joinpath("dbos_schema.json").read_text())
    else:
        payload = json.loads(path.read_text())
    return from_json(payload)


def argus_only(dump: SchemaDump) -> SchemaDump:
    """Filter a snapshot to columns where `argus=True`. Tables with zero matches are dropped."""
    filtered_tables: list[TableInfo] = []
    for table in dump.tables:
        marked = tuple(c for c in table.columns if c.argus)
        if marked:
            filtered_tables.append(replace(table, columns=marked))
    return replace(dump, tables=tuple(filtered_tables))
