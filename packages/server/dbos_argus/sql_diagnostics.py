"""Schema diagnostics: load the packaged snapshot, reflect the live DB through
the adapter, diff them.

The actual machinery is split between `schema_dump` (load the JSON snapshot
into a `SchemaDump`), the adapter's `reflect_schema()` (per-dialect live
reflection), and `schema_diff` (a generic dump-vs-dump comparator). This
module is the wiring the FastAPI endpoint calls.

The packaged snapshot in `data/dbos_schema.json` is the *full* DBOS schema
with per-column `argus: true|false` markers. For runtime diagnostics we filter
to the argus-marked subset before diffing against the live DB; the unmarked
columns are tracked by the CI watchdog only.
"""

from __future__ import annotations

from .db.base import ArgusDB
from .schema_diff import SchemaIssue, diff_schemas
from .schema_dump import argus_only, load_full_dump

__all__ = ["SchemaIssue", "inspect_dbos_schema"]


async def inspect_dbos_schema(db: ArgusDB) -> list[SchemaIssue]:
    expected = argus_only(load_full_dump())
    actual = await db.reflect_schema(schema=expected.schema)
    return diff_schemas(expected, actual)
