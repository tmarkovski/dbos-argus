"""Canonical DBOS Transact workflow statuses.

The set is finite and defined upstream by `dbos.WorkflowStatusString`
(see `dbos/_sys_db.py`). This module mirrors it for the SQL layer so we
don't take a runtime dep on `dbos` (per architecture invariant #1) yet still
have a single source of truth — change the list here and queries that
embed status strings will pick it up.

Mirror policy: if upstream adds a value, update this list, the console's
`apps/console/src/lib/workflow-status.ts`, and the color cases in
`apps/console/src/lib/workflow-tree.ts` and `WorkflowTimeline.svelte`.
`tests/test_workflow_status.py` fails when this list and the installed
`dbos.WorkflowStatusString` disagree.
"""

from __future__ import annotations

from typing import Literal

WorkflowStatus = Literal[
    "PENDING",
    "ENQUEUED",
    "DELAYED",
    "SUSPENDED",
    "SUCCESS",
    "ERROR",
    "CANCELLED",
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
]

# Statuses that mean "not yet terminal": in flight, queued, delayed, or
# suspended (DBOS 3.5+ parks a workflow waiting in recv, sleep or on another
# workflow's result as SUSPENDED instead of holding a thread).
ACTIVE_STATUSES: tuple[WorkflowStatus, ...] = ("PENDING", "ENQUEUED", "DELAYED", "SUSPENDED")

# Statuses that mean "execution finished" — success or any failure mode.
TERMINAL_STATUSES: tuple[WorkflowStatus, ...] = (
    "SUCCESS",
    "ERROR",
    "CANCELLED",
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
)

# Statuses that count as "failed" for dashboard purposes (errors + recovery exhaustion).
ERROR_STATUSES: tuple[WorkflowStatus, ...] = ("ERROR", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")


def _sql_in(values: tuple[str, ...]) -> str:
    """Render a tuple of status literals as a SQL `(...)` IN-list."""
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


# Pre-rendered IN-lists for embedding into SQL strings. (Values are static
# enum literals, so f-string composition is safe — not user input.)
ACTIVE_STATUSES_SQL = _sql_in(ACTIVE_STATUSES)
TERMINAL_STATUSES_SQL = _sql_in(TERMINAL_STATUSES)
ERROR_STATUSES_SQL = _sql_in(ERROR_STATUSES)
