"""Schema diagnostics: load the packaged snapshot, reflect the live DB through
the adapter, diff them, and grade the DB's DBOS schema revision.

The actual machinery is split between `schema_dump` (load the JSON snapshot
into a `SchemaDump`), the adapter's `reflect_schema()` (per-dialect live
reflection), `schema_diff` (a generic dump-vs-dump comparator), and `compat`
(revision-to-Argus-version mapping). This module is the wiring the FastAPI
endpoint calls.

The packaged snapshot in `data/dbos_schema.json` is the *full* DBOS schema
with per-column `argus: true|false` markers. For runtime diagnostics we filter
to the argus-marked subset before diffing against the live DB; the unmarked
columns are tracked by the CI watchdog only.

The two halves answer different questions and are both worth reporting: the diff
says *what* is missing, the compat report says *which Argus version to run
instead*. The diff also stands alone when the revision can't be read at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from .compat import CompatReport, resolve_compat
from .db.base import ArgusDB
from .schema_diff import SchemaIssue, diff_schemas
from .schema_dump import argus_only, load_full_dump

__all__ = ["DbosSchemaReport", "SchemaIssue", "inspect_dbos_schema"]


@dataclass(frozen=True)
class DbosSchemaReport:
    issues: list[SchemaIssue]
    compat: CompatReport


async def inspect_dbos_schema(db: ArgusDB) -> DbosSchemaReport:
    expected = argus_only(load_full_dump())
    actual = await db.reflect_schema(schema=expected.schema)
    revision = await db.dbos_schema_revision()
    return DbosSchemaReport(
        issues=diff_schemas(expected, actual),
        compat=resolve_compat(db.dialect, revision),
    )
