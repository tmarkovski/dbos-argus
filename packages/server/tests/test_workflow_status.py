"""Drift guard: Argus' status mirror against the DBOS release in the lockfile.

The schema watchdog compares tables and columns, so a new status value (a
behavioural change stored in an existing text column) gets past it. These
tests fail as soon as the dev fixture is bumped to a DBOS release whose
`WorkflowStatusString` differs from `dbos_argus.workflow_status`.
"""

from __future__ import annotations

from typing import get_args

from dbos_argus.workflow_status import (
    ACTIVE_STATUSES,
    ERROR_STATUSES,
    TERMINAL_STATUSES,
    WorkflowStatus,
)


def _upstream_statuses() -> set[str]:
    from dbos import WorkflowStatusString

    return {s.value for s in WorkflowStatusString}


def test_status_literal_matches_dbos() -> None:
    assert set(get_args(WorkflowStatus)) == _upstream_statuses()


def test_active_and_terminal_partition_every_status() -> None:
    active, terminal = set(ACTIVE_STATUSES), set(TERMINAL_STATUSES)
    assert not active & terminal
    assert active | terminal == set(get_args(WorkflowStatus))


def test_active_statuses_match_dbos() -> None:
    # DBOS' own notion of "not complete yet"; anything else has a result.
    from dbos._sys_db import workflow_is_active

    upstream_active = {s for s in _upstream_statuses() if workflow_is_active(s)}
    assert set(ACTIVE_STATUSES) == upstream_active


def test_error_statuses_are_terminal() -> None:
    assert set(ERROR_STATUSES) <= set(TERMINAL_STATUSES)
