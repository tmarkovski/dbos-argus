import { STATUS_LABELS, type WorkflowStatus } from "./workflow-status";

export type Workflow = {
  workflow_id: string;
  parent_workflow_id: string | null;
  name: string | null;
  status: string | null;
  queue_name: string | null;
  executor_id: string | null;
  priority: number;
  started_at: string;
  updated_at: string;
  depth: number;
  operation_count: number;
};

// For each row, a `lineage` array of booleans of length == depth.
// Entry at index i (i < depth-1) says "draw vertical line at this column"
// (true) vs "empty space" (false) based on whether the ancestor at depth
// i+1 has a next sibling. Entry at index depth-1 (the row's own connector
// column) is true for ├─ and false for └─.
export type TreeRow = Workflow & { lineage: boolean[] };

export function computeLineage(workflows: Workflow[]): TreeRow[] {
  const byId = new Map(workflows.map((w) => [w.workflow_id, w]));

  // Rows arrive in DFS order: for each row R, scan forward — the first row
  // with depth <= R.depth is either R's next sibling (depth ==) or breaks
  // out of R's subtree (depth <).
  const hasNext = new Map<string, boolean>();
  for (let i = 0; i < workflows.length; i++) {
    const r = workflows[i];
    let flag = false;
    for (let j = i + 1; j < workflows.length; j++) {
      const q = workflows[j];
      if (q.depth < r.depth) break;
      if (q.depth === r.depth) {
        flag = q.parent_workflow_id === r.parent_workflow_id;
        break;
      }
    }
    hasNext.set(r.workflow_id, flag);
  }

  return workflows.map((w) => {
    // chain = [rootAncestor, ..., parent, w] ordered by increasing depth.
    const chain: Workflow[] = [w];
    let cur: Workflow | undefined = w;
    while (cur?.parent_workflow_id) {
      const p = byId.get(cur.parent_workflow_id);
      if (!p) break;
      chain.unshift(p);
      cur = p;
    }
    const lineage: boolean[] = [];
    for (let i = 0; i < w.depth; i++) {
      const ancestor = chain[i + 1];
      lineage.push(hasNext.get(ancestor.workflow_id) ?? false);
    }
    return { ...w, lineage };
  });
}

// Status colors. Inputs are the literal strings from the API — see
// `./workflow-status.ts` for the canonical set (`WorkflowStatus`). Unknown
// values fall through to a neutral muted style. Both helpers route through
// the `--status-*` design tokens (see app.css) so themed presets cascade.
export function statusBadgeClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS") return "bg-status-success/15 text-status-success";
  if (s === "ENQUEUED") return "bg-status-queued/15 text-status-queued";
  if (s === "PENDING" || s === "DELAYED")
    return "bg-status-running/15 text-status-running";
  if (s === "CANCELLED") return "bg-status-warning/15 text-status-warning";
  if (s === "ERROR" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
    return "bg-status-error/15 text-status-error";
  return "bg-muted text-muted-foreground";
}

// Display label for a workflow status. Routes known DBOS statuses through
// STATUS_LABELS (so e.g. MAX_RECOVERY_ATTEMPTS_EXCEEDED → "Max retries");
// falls back to title-casing the raw value. Returns "—" for null/empty.
export function formatStatus(status: string | null | undefined): string {
  if (!status) return "—";
  const known = STATUS_LABELS[status as WorkflowStatus];
  if (known) return known;
  return status
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function statusDotClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS") return "bg-status-success";
  if (s === "ENQUEUED") return "bg-status-queued";
  if (s === "PENDING" || s === "DELAYED") return "bg-status-running";
  if (s === "CANCELLED") return "bg-status-warning";
  if (s === "ERROR" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED") return "bg-status-error";
  return "bg-muted-foreground/40";
}
