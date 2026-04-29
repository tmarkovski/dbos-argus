"""Generic dump-vs-dump schema diff.

Given an expected `SchemaDump` (loaded from the package's JSON snapshot) and an
actual one (reflected from the live DB), produce a list of `SchemaIssue`s for
every required table or column that's missing or has an incompatible type.

The diff is deliberately one-sided: extra tables/columns present in the actual
DB are ignored — Argus only cares about what *it* depends on. Type comparison
goes through a small synonym table that captures the well-known PG aliases
(text/character varying/character) so a snapshot taken on one DBOS install
doesn't trip on superficial differences against another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .schema_dump import SchemaDump

# information_schema reports these three as distinct `data_type` values, but
# they're functionally interchangeable for read-only consumers like Argus.
# Any other type-equivalence the diff should tolerate goes here.
_TYPE_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"text", "character varying", "character"}),
)


def types_match(expected: str, actual: str) -> bool:
    """True iff the two PG `data_type` strings are interchangeable for our purposes."""
    if expected == actual:
        return True
    return any(expected in group and actual in group for group in _TYPE_SYNONYMS)


@dataclass(frozen=True)
class SchemaIssue:
    kind: Literal["missing_table", "missing_column", "wrong_type"]
    table_name: str
    column_name: str | None
    expected_type: str | None
    actual_type: str | None
    detail: str


def diff_schemas(expected: SchemaDump, actual: SchemaDump) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    actual_tables = actual.table_index()

    for expected_table in expected.tables:
        actual_table = actual_tables.get(expected_table.name)
        if actual_table is None:
            issues.append(
                SchemaIssue(
                    kind="missing_table",
                    table_name=expected_table.name,
                    column_name=None,
                    expected_type=None,
                    actual_type=None,
                    detail=f"Missing required table {expected.schema}.{expected_table.name}.",
                )
            )
            continue

        actual_columns = {c.name: c for c in actual_table.columns}
        for expected_column in expected_table.columns:
            actual_column = actual_columns.get(expected_column.name)
            if actual_column is None:
                issues.append(
                    SchemaIssue(
                        kind="missing_column",
                        table_name=expected_table.name,
                        column_name=expected_column.name,
                        expected_type=expected_column.data_type,
                        actual_type=None,
                        detail=(
                            f"Missing required column "
                            f"{expected.schema}.{expected_table.name}.{expected_column.name}."
                        ),
                    )
                )
                continue
            if not types_match(expected_column.data_type, actual_column.data_type):
                issues.append(
                    SchemaIssue(
                        kind="wrong_type",
                        table_name=expected_table.name,
                        column_name=expected_column.name,
                        expected_type=expected_column.data_type,
                        actual_type=actual_column.data_type,
                        detail=(
                            f"Column {expected.schema}.{expected_table.name}."
                            f"{expected_column.name} has type {actual_column.data_type}; "
                            f"expected {expected_column.data_type}."
                        ),
                    )
                )

    return issues
