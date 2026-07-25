"""DBOS schema-revision compatibility.

Argus reads a moving set of `dbos.*` columns, so a database last migrated by an
older DBOS release can be missing something Argus queries — the symptom is an
opaque "column does not exist" error on the workflow list or detail page. This
module turns that into an actionable instruction: *pin Argus to version X*.

The signal is `dbos.dbos_migrations.version`, DBOS Transact's own schema
revision counter — a 1-based count of applied migrations (DBOS applies them with
`enumerate(migrations, 1)`) that only ever grows. That integer, not the `dbos`
package version, is the right key:

- The package version is not in the database at all. `dbos.application_versions`
  holds the *host application's* version, not DBOS'.
- The package version can lie. Upgrading `dbos` without restarting the app that
  runs the migrations leaves the database behind what the library advertises.
- A missing column is a migration fact, so the migration counter answers the
  question directly instead of by proxy.

Revisions are **per-dialect**. DBOS' Postgres and SQLite migration lists diverge
(SQLite has no counterpart for a handful of Postgres-only migrations), so the
same integer means different things on each backend and every floor below is
recorded twice.

Maintenance
-----------
When `main.py` starts reading a column that arrived in a newer DBOS migration:

1. Flip the column to `"argus": true` in `data/dbos_schema.json`.
2. Append a `CompatStep` below with the new per-dialect revisions, and set the
   previously-final step's `max_argus_version` to the last released Argus
   version — the newest one that still works without the new column.

`test_compat.py` asserts the ladder stays internally consistent and that the
final step matches what the snapshot actually requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Dialect = Literal["postgres", "sqlite"]

__all__ = [
    "COMPAT_STEPS",
    "CompatReport",
    "CompatStep",
    "Dialect",
    "required_revision",
    "resolve_compat",
]


@dataclass(frozen=True)
class CompatStep:
    """One point in Argus' history where the required DBOS schema revision rose.

    `max_argus_version` is the newest Argus release that runs against a database
    sitting at this step — i.e. the version to pin. It is `None` on the final
    step, which is the requirement the current build enforces: a database that
    reaches it needs no pin at all.
    """

    postgres: int
    sqlite: int
    max_argus_version: str | None
    # DBOS release that first shipped these revisions. Human-readable hint only;
    # never used for comparisons.
    dbos_version: str
    # Columns this step started reading, as `table.column`, for the message.
    requires: tuple[str, ...]

    def revision_for(self, dialect: Dialect) -> int:
        return self.sqlite if dialect == "sqlite" else self.postgres


# Ascending by revision. See "Maintenance" above before editing.
COMPAT_STEPS: tuple[CompatStep, ...] = (
    CompatStep(
        postgres=0,
        sqlite=0,
        max_argus_version="0.0.27",
        dbos_version="2.19.0",
        requires=(),
    ),
    CompatStep(
        postgres=36,
        sqlite=33,
        max_argus_version="0.0.28",
        dbos_version="2.23.0",
        requires=("workflow_status.completed_at",),
    ),
    CompatStep(
        postgres=41,
        sqlite=36,
        max_argus_version=None,
        dbos_version="2.25.0",
        requires=("workflow_status.attributes", "workflow_status.schedule_name"),
    ),
)


def required_revision(dialect: Dialect) -> int:
    """Lowest `dbos_migrations.version` this Argus build can read."""
    return COMPAT_STEPS[-1].revision_for(dialect)


@dataclass(frozen=True)
class CompatReport:
    dialect: Dialect
    # None when `dbos_migrations` is absent or unreadable: either a fresh
    # database no DBOS app has migrated yet, or a legacy Alembic-managed one
    # that predates the migrations table. Both leave the column diff as the
    # only authority, so we make no claim.
    revision: int | None
    required_revision: int
    # False only when the revision is known *and* below what Argus needs.
    compatible: bool
    # Newest Argus release that works against this database. None when the
    # database is already current (or its revision is unknown).
    recommended_argus_version: str | None
    # DBOS release to upgrade to as the alternative to pinning Argus.
    recommended_dbos_version: str | None
    # `table.column` entries Argus reads that this database cannot have.
    missing_columns: tuple[str, ...]
    # Populated iff `compatible` is False.
    message: str | None


def resolve_compat(dialect: Dialect, revision: int | None) -> CompatReport:
    """Compare a database's DBOS schema revision against what Argus requires.

    Returns a compatible report when `revision` is None — an unknown revision is
    not evidence of a problem, and `sql_diagnostics` still reports the concrete
    missing columns.
    """
    required = required_revision(dialect)

    if revision is None or revision >= required:
        return CompatReport(
            dialect=dialect,
            revision=revision,
            required_revision=required,
            compatible=True,
            recommended_argus_version=None,
            recommended_dbos_version=None,
            missing_columns=(),
            message=None,
        )

    # Newest step this database satisfies decides the pin; every step above it
    # is unmet, so their columns are collectively missing.
    satisfied = COMPAT_STEPS[0]
    unmet: list[CompatStep] = []
    for step in COMPAT_STEPS:
        if revision >= step.revision_for(dialect):
            satisfied = step
        else:
            unmet.append(step)

    # The upgrade advice names the DBOS version that clears *every* unmet step,
    # not just the next one — the final step is Argus' actual requirement, so
    # anything lower would leave the user still broken after upgrading.
    target = COMPAT_STEPS[-1]
    missing = [column for step in unmet for column in step.requires]

    pin = satisfied.max_argus_version
    columns = ", ".join(missing)
    remedy = f"upgrade DBOS to {target.dbos_version} or newer and let your app run its migrations"
    if pin is None:
        # Unreachable with the current ladder (only the final step carries
        # None, and reaching it means compatible). Kept so a future edit that
        # sets None on a middle step degrades to advice instead of a crash.
        pin_advice = "no earlier Argus release is recorded for this revision"
    else:
        pin_advice = f"pin Argus with `pip install 'dbos-argus=={pin}'`"

    return CompatReport(
        dialect=dialect,
        revision=revision,
        required_revision=required,
        compatible=False,
        recommended_argus_version=pin,
        recommended_dbos_version=target.dbos_version,
        missing_columns=tuple(missing),
        message=(
            f"This database is at DBOS schema revision {revision}; "
            f"Argus needs {required}. Missing: {columns}. "
            f"Either {remedy}, or {pin_advice}."
        ),
    )
