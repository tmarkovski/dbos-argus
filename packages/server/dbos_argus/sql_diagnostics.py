"""Schema diagnostics: load the expected snapshot, dump the live DB, diff them.

The actual machinery is split between `schema_dump` (extract a SchemaDump from
either a JSON snapshot or a live AsyncConnection) and `schema_diff` (a generic
dump-vs-dump comparator). This module is just the wiring that the FastAPI
endpoint calls into.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from .schema_diff import SchemaIssue, diff_schemas
from .schema_dump import dump_live_schema, load_expected_dump

__all__ = ["SchemaIssue", "inspect_dbos_schema"]


async def inspect_dbos_schema(conn: AsyncConnection) -> list[SchemaIssue]:
    expected = load_expected_dump()
    actual = await dump_live_schema(conn, schema=expected.schema)
    return diff_schemas(expected, actual)
