/**
 * Canonical DBOS Transact workflow statuses.
 *
 * The set is finite and defined upstream by `dbos.WorkflowStatusString`
 * (see `dbos/_sys_db.py:72`). Anything that filters, colors, or labels a
 * workflow status should consume these constants instead of hard-coding the
 * literals.
 *
 * Mirror policy: if upstream adds a value here, update this list AND the
 * matching color cases in `workflow-tree.ts`.
 */

export const WORKFLOW_STATUSES = [
  "PENDING",
  "ENQUEUED",
  "DELAYED",
  "SUCCESS",
  "ERROR",
  "CANCELLED",
  "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
] as const;

export type WorkflowStatus = (typeof WORKFLOW_STATUSES)[number];

/** Statuses that mean "not yet terminal" — currently in-flight / queued / sleeping. */
export const ACTIVE_STATUSES = ["PENDING", "ENQUEUED", "DELAYED"] as const satisfies readonly WorkflowStatus[];

/** Statuses that mean "execution finished" — success or failure mode. */
export const TERMINAL_STATUSES = [
  "SUCCESS",
  "ERROR",
  "CANCELLED",
  "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
] as const satisfies readonly WorkflowStatus[];

/** Display labels for filter UIs. Keep alongside `WORKFLOW_STATUSES`. */
export const STATUS_LABELS: Record<WorkflowStatus, string> = {
  PENDING: "Pending",
  ENQUEUED: "Enqueued",
  DELAYED: "Delayed",
  SUCCESS: "Success",
  ERROR: "Error",
  CANCELLED: "Cancelled",
  MAX_RECOVERY_ATTEMPTS_EXCEEDED: "Max retries",
};
