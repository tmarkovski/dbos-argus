"""Compare the live DBOS Postgres schema against the checked-in snapshot.

Used by the `dbos-schema-watch` GH Actions workflow. Steps:

1. Reflect the live `dbos.*` schema from `--db-url` into a `SchemaDump`.
2. Load the existing snapshot at `--existing`.
3. Build a regenerated snapshot: take the live schema as the source of
   truth for shape and types, but carry forward the `argus: true|false`
   flag from the existing snapshot. New columns default to `argus: false`.
4. Compute deltas between existing and regenerated, bucketed by impact:
   - **Breaking for Argus**: removed/retyped columns that had `argus=true`.
   - **Untracked**: everything else (new/removed/retyped columns we don't
     read, new/removed tables).
5. If anything to report, write `--report-file` (Markdown) and
   `--regenerated-file` (JSON), exit 1. Otherwise exit 0.

The Markdown report is fed into `gh issue create --body-file`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

# Add packages/server to sys.path so we can import the runtime modules without
# installing the wheel in CI.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "packages" / "server"))

from dbos_argus.schema_diff import types_match  # noqa: E402
from dbos_argus.schema_dump import (  # noqa: E402
    ColumnInfo,
    SchemaDump,
    TableInfo,
    dump_live_schema,
    from_json,
    to_json,
)


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str

    def __str__(self) -> str:
        return f"{self.table}.{self.column}"


@dataclass(frozen=True)
class TypedColumnDelta:
    table: str
    column: str
    old: str
    new: str
    argus: bool


@dataclass(frozen=True)
class ColumnAddRemove:
    table: str
    column: str
    data_type: str
    argus: bool


@dataclass
class Deltas:
    added_tables: list[str]
    # Each removed table carries its column list so we can decide whether
    # losing it is breaking-for-Argus or merely informational.
    removed_tables: list[TableInfo]
    added_columns: list[ColumnAddRemove]
    removed_columns: list[ColumnAddRemove]
    retyped_columns: list[TypedColumnDelta]

    def empty(self) -> bool:
        return not (
            self.added_tables
            or self.removed_tables
            or self.added_columns
            or self.removed_columns
            or self.retyped_columns
        )

    def breaking(self) -> list[str]:
        """Argus-tracked changes that likely need code edits in main.py."""
        bad: list[str] = []
        for col in self.removed_columns:
            if col.argus:
                bad.append(f"`dbos.{col.table}.{col.column}` removed (was {col.data_type})")
        for col in self.retyped_columns:
            if col.argus:
                bad.append(f"`dbos.{col.table}.{col.column}` retyped: {col.old} → {col.new}")
        for table in self.removed_tables:
            if any(c.argus for c in table.columns):
                tracked = [c.name for c in table.columns if c.argus]
                bad.append(
                    f"`dbos.{table.name}` table removed "
                    f"(tracked columns lost: {', '.join(tracked)})"
                )
        return bad


def _build_regenerated(
    existing: SchemaDump,
    actual: SchemaDump,
    new_dbos_version: str,
) -> SchemaDump:
    existing_argus: dict[ColumnRef, bool] = {}
    for table in existing.tables:
        for column in table.columns:
            existing_argus[ColumnRef(table.name, column.name)] = column.argus

    new_meta = dict(existing.meta)
    new_meta["dbos_version"] = new_dbos_version

    new_tables: list[TableInfo] = []
    for actual_table in actual.tables:
        new_columns = tuple(
            ColumnInfo(
                name=c.name,
                data_type=c.data_type,
                argus=existing_argus.get(ColumnRef(actual_table.name, c.name), False),
            )
            for c in actual_table.columns
        )
        new_tables.append(TableInfo(name=actual_table.name, columns=new_columns))

    return SchemaDump(schema=existing.schema, tables=tuple(new_tables), meta=new_meta)


def _compute_deltas(existing: SchemaDump, regenerated: SchemaDump) -> Deltas:
    existing_tables = existing.table_index()
    regen_tables = regenerated.table_index()

    added_tables = sorted(set(regen_tables) - set(existing_tables))
    removed_tables = [
        existing_tables[name] for name in sorted(set(existing_tables) - set(regen_tables))
    ]

    added_columns: list[ColumnAddRemove] = []
    removed_columns: list[ColumnAddRemove] = []
    retyped_columns: list[TypedColumnDelta] = []

    for table_name in sorted(set(existing_tables) & set(regen_tables)):
        existing_cols = {c.name: c for c in existing_tables[table_name].columns}
        regen_cols = {c.name: c for c in regen_tables[table_name].columns}

        for added in sorted(set(regen_cols) - set(existing_cols)):
            c = regen_cols[added]
            added_columns.append(ColumnAddRemove(table_name, added, c.data_type, c.argus))
        for removed in sorted(set(existing_cols) - set(regen_cols)):
            c = existing_cols[removed]
            removed_columns.append(ColumnAddRemove(table_name, removed, c.data_type, c.argus))
        for shared in sorted(set(existing_cols) & set(regen_cols)):
            old, new = existing_cols[shared], regen_cols[shared]
            if not types_match(old.data_type, new.data_type):
                retyped_columns.append(
                    TypedColumnDelta(table_name, shared, old.data_type, new.data_type, old.argus)
                )

    return Deltas(
        added_tables=added_tables,
        removed_tables=removed_tables,
        added_columns=added_columns,
        removed_columns=removed_columns,
        retyped_columns=retyped_columns,
    )


def _format_report(
    old_version: str,
    new_version: str,
    deltas: Deltas,
    regenerated_json: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# DBOS schema drift: {old_version} → {new_version}")
    lines.append("")

    breaking = deltas.breaking()
    if breaking:
        lines.append(f"## 🛑 Breaking for Argus ({len(breaking)})")
        lines.append("")
        lines.append(
            "These changes affect columns the Argus backend actively reads. "
            "Fixing them likely requires code edits in "
            "`packages/server/dbos_argus/main.py` in addition to bumping the snapshot."
        )
        lines.append("")
        for entry in breaking:
            lines.append(f"- {entry}")
        lines.append("")

    untracked_removed_tables = [
        t for t in deltas.removed_tables if not any(c.argus for c in t.columns)
    ]
    untracked_removed = [c for c in deltas.removed_columns if not c.argus]
    untracked_retyped = [c for c in deltas.retyped_columns if not c.argus]
    untracked_count = (
        len(deltas.added_tables)
        + len(untracked_removed_tables)
        + len(deltas.added_columns)
        + len(untracked_removed)
        + len(untracked_retyped)
    )
    if untracked_count:
        lines.append(f"## 📊 Untracked DBOS changes ({untracked_count})")
        lines.append("")
        lines.append(
            "DBOS shipped these — Argus doesn't currently read them. "
            "Adopt one by flipping `argus: true` in the snapshot and adding queries."
        )
        lines.append("")
        if deltas.added_tables:
            lines.append("### Added tables")
            for t in deltas.added_tables:
                lines.append(f"- `dbos.{t}`")
            lines.append("")
        if untracked_removed_tables:
            lines.append("### Removed tables (not tracked by Argus)")
            for t in untracked_removed_tables:
                lines.append(f"- `dbos.{t.name}`")
            lines.append("")
        if deltas.added_columns:
            lines.append("### Added columns")
            for c in deltas.added_columns:
                lines.append(f"- `dbos.{c.table}.{c.column} ({c.data_type})`")
            lines.append("")
        if untracked_removed:
            lines.append("### Removed columns (not tracked by Argus)")
            for c in untracked_removed:
                lines.append(f"- `dbos.{c.table}.{c.column}` (was {c.data_type})")
            lines.append("")
        if untracked_retyped:
            lines.append("### Retyped columns (not tracked by Argus)")
            for c in untracked_retyped:
                lines.append(f"- `dbos.{c.table}.{c.column}`: {c.old} → {c.new}")
            lines.append("")

    lines.append("## Regenerated snapshot")
    lines.append("")
    lines.append(
        "Replace `packages/server/dbos_argus/data/dbos_schema.json` with the "
        "JSON below. If the **Breaking for Argus** section above is empty, this "
        "is a pure snapshot bump; otherwise pair the snapshot replacement with "
        "the necessary edits to `main.py`."
    )
    lines.append("")
    lines.append("<details><summary>dbos_schema.json</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(regenerated_json)
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


async def _async_main(args: argparse.Namespace) -> int:
    existing_payload = json.loads(Path(args.existing).read_text())
    existing = from_json(existing_payload)
    old_version = existing.meta.get("dbos_version", "unknown")

    engine = create_async_engine(args.db_url)
    try:
        async with engine.connect() as conn:
            actual = await dump_live_schema(conn, schema=existing.schema)
    finally:
        await engine.dispose()

    regenerated = _build_regenerated(existing, actual, args.new_dbos_version)
    deltas = _compute_deltas(existing, regenerated)

    if deltas.empty():
        print("No schema drift detected.", file=sys.stderr)
        return 0

    regenerated_json = json.dumps(to_json(regenerated), indent=2)
    Path(args.regenerated_file).write_text(regenerated_json + "\n")

    report = _format_report(old_version, args.new_dbos_version, deltas, regenerated_json)
    Path(args.report_file).write_text(report)

    print(
        f"Drift detected: {len(deltas.breaking())} breaking, "
        f"{len(deltas.added_tables)} new tables, "
        f"{len(deltas.added_columns)} new columns.",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--db-url",
        required=True,
        help="SQLAlchemy async URL (postgresql+asyncpg://...) for the bootstrapped DBOS DB.",
    )
    parser.add_argument(
        "--existing",
        default="packages/server/dbos_argus/data/dbos_schema.json",
        help="Path to the checked-in snapshot.",
    )
    parser.add_argument(
        "--new-dbos-version",
        required=True,
        help="DBOS version that produced the live schema (goes into meta.dbos_version).",
    )
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--regenerated-file", required=True)
    args = parser.parse_args()
    sys.exit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
