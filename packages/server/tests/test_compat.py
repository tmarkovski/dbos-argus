"""Tests for the DBOS schema-revision compatibility ladder.

Three layers:
  - Ladder invariants (`COMPAT_STEPS` is well-formed).
  - `resolve_compat` behaviour across both dialects and the unknown-revision case.
  - A drift guard that replays DBOS' own SQLite migrations to derive the floor
    empirically and compare it against what `compat.py` declares. Skipped when
    `dbos` isn't importable so the suite still runs against a bare install.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from dbos_argus.compat import COMPAT_STEPS, Dialect, required_revision, resolve_compat
from dbos_argus.schema_dump import argus_only, load_full_dump

DIALECTS: tuple[Dialect, ...] = ("postgres", "sqlite")


# --- ladder invariants -------------------------------------------------------


def test_steps_are_ascending_per_dialect() -> None:
    for dialect in DIALECTS:
        revisions = [s.revision_for(dialect) for s in COMPAT_STEPS]
        assert revisions == sorted(revisions), f"{dialect} revisions must ascend"
        assert len(set(revisions)) == len(revisions), f"{dialect} revisions must be distinct"


def test_only_the_final_step_has_no_pin() -> None:
    # A None `max_argus_version` means "current build" — only meaningful on the
    # last step, since every earlier one must name a release to fall back to.
    assert COMPAT_STEPS[-1].max_argus_version is None
    assert all(s.max_argus_version is not None for s in COMPAT_STEPS[:-1])


def test_required_revision_tracks_the_final_step() -> None:
    for dialect in DIALECTS:
        assert required_revision(dialect) == COMPAT_STEPS[-1].revision_for(dialect)


def test_first_step_is_reachable_by_any_database() -> None:
    # The base step must be satisfied by revision 0 so `resolve_compat` always
    # has a step to fall back to.
    for dialect in DIALECTS:
        assert COMPAT_STEPS[0].revision_for(dialect) == 0


# --- resolve_compat ----------------------------------------------------------


@pytest.mark.parametrize("dialect", DIALECTS)
def test_current_revision_is_compatible(dialect: Dialect) -> None:
    report = resolve_compat(dialect, required_revision(dialect))
    assert report.compatible
    assert report.message is None
    assert report.recommended_argus_version is None
    assert report.missing_columns == ()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_future_revision_is_compatible(dialect: Dialect) -> None:
    # A DBOS newer than this build only adds columns we don't read.
    report = resolve_compat(dialect, required_revision(dialect) + 50)
    assert report.compatible
    assert report.recommended_argus_version is None


@pytest.mark.parametrize("dialect", DIALECTS)
def test_unknown_revision_makes_no_claim(dialect: Dialect) -> None:
    # No dbos_migrations table: fresh DB, or legacy Alembic-managed. The column
    # diff is the authority, so compat must not cry wolf.
    report = resolve_compat(dialect, None)
    assert report.compatible
    assert report.revision is None
    assert report.message is None


@pytest.mark.parametrize("dialect", DIALECTS)
def test_one_below_floor_recommends_the_previous_release(dialect: Dialect) -> None:
    floor = required_revision(dialect)
    report = resolve_compat(dialect, floor - 1)
    assert not report.compatible
    assert report.revision == floor - 1
    assert report.required_revision == floor
    assert report.recommended_argus_version == COMPAT_STEPS[-2].max_argus_version
    # Only the final step is unmet, so only its columns are reported missing.
    assert report.missing_columns == COMPAT_STEPS[-1].requires


@pytest.mark.parametrize("dialect", DIALECTS)
def test_ancient_revision_accumulates_every_unmet_step(dialect: Dialect) -> None:
    report = resolve_compat(dialect, 1)
    assert not report.compatible
    assert report.recommended_argus_version == COMPAT_STEPS[0].max_argus_version
    # Union of every step above the base, in ladder order.
    expected = tuple(c for step in COMPAT_STEPS[1:] for c in step.requires)
    assert report.missing_columns == expected


@pytest.mark.parametrize("dialect", DIALECTS)
def test_upgrade_advice_clears_every_unmet_step(dialect: Dialect) -> None:
    # Pointing at the *next* step's DBOS version would leave the user still
    # broken; the advice must name the version that satisfies Argus outright.
    report = resolve_compat(dialect, 1)
    assert report.recommended_dbos_version == COMPAT_STEPS[-1].dbos_version


@pytest.mark.parametrize("dialect", DIALECTS)
def test_message_is_actionable(dialect: Dialect) -> None:
    floor = required_revision(dialect)
    report = resolve_compat(dialect, floor - 1)
    assert report.message is not None
    assert str(floor) in report.message
    assert str(floor - 1) in report.message
    assert report.recommended_argus_version is not None
    # The pin is the whole point of the message.
    assert f"dbos-argus=={report.recommended_argus_version}" in report.message
    for column in report.missing_columns:
        assert column in report.message


def test_dialects_have_distinct_floors() -> None:
    # Postgres and SQLite migration lists diverge; a single shared number would
    # silently mis-grade one of the backends.
    assert required_revision("postgres") != required_revision("sqlite")


# --- drift guard against DBOS' real migrations -------------------------------


def _sqlite_columns_after(n: int) -> dict[str, set[str]]:
    """Apply DBOS' first `n` SQLite migrations to an in-memory DB and return
    `{table: {column, ...}}`. Uses DBOS' own migration SQL, so the result is
    exactly what a real DBOS app at revision `n` would have."""
    from dbos._migration import sqlite_migrations

    conn = sqlite3.connect(":memory:")
    try:
        for migration in sqlite_migrations[:n]:
            for statement in (s.strip() for s in migration.split(";") if s.strip()):
                conn.execute(statement)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}
    finally:
        conn.close()


def _missing_argus_columns(present: dict[str, set[str]]) -> set[str]:
    """`table.column` entries the snapshot marks argus-tracked but `present` lacks."""
    expected = argus_only(load_full_dump())
    return {
        f"{table.name}.{column.name}"
        for table in expected.tables
        for column in table.columns
        if column.name not in present.get(table.name, set())
    }


def test_readme_table_matches_the_ladder() -> None:
    """The README's compatibility table is the artifact users actually read, and
    nothing else keeps it honest. Assert every step's numbers and pin appear in
    it, so a `COMPAT_STEPS` edit can't silently leave the docs behind."""
    readme = Path(__file__).resolve().parents[3] / "README.md"
    section = readme.read_text().split("## Which Argus version do I need?", 1)
    assert len(section) == 2, "README lost the compatibility section"
    table = section[1].split("\n## ", 1)[0]

    for step in COMPAT_STEPS:
        if step.max_argus_version is None:
            # Current build: the table says "latest" rather than a pin.
            assert f"≥ {step.postgres}" in table
            assert f"≥ {step.sqlite}" in table
            continue
        assert step.max_argus_version in table, (
            f"README table is missing the `{step.max_argus_version}` row"
        )
        # Each non-final step bounds a range whose upper edge is the next step's
        # revision minus one; the lower edge is the step's own revision.
        if step.postgres:
            assert str(step.postgres) in table
        if step.sqlite:
            assert str(step.sqlite) in table


def test_declared_sqlite_floor_is_exact() -> None:
    """The declared SQLite floor must be the *lowest* revision that satisfies
    every argus-tracked column: sufficient at the floor, and insufficient one
    below it.

    This is the guard the maintenance note in `compat.py` relies on. Marking a
    new column `argus: true` without appending a `CompatStep` fails the first
    assert; bumping the floor higher than necessary fails the second.
    """
    pytest.importorskip("dbos", reason="drift guard needs DBOS' migration SQL")
    floor = required_revision("sqlite")

    missing_at_floor = _missing_argus_columns(_sqlite_columns_after(floor))
    assert missing_at_floor == set(), (
        f"SQLite revision {floor} does not provide argus-tracked columns "
        f"{sorted(missing_at_floor)} — append a CompatStep in compat.py"
    )

    missing_below = _missing_argus_columns(_sqlite_columns_after(floor - 1))
    assert missing_below, (
        f"SQLite revision {floor - 1} already provides every argus-tracked "
        f"column, so the declared floor {floor} is higher than necessary"
    )
