export type Workflow = {
  workflow_id: string;
  parent_workflow_id: string | null;
  name: string | null;
  status: string | null;
  queue_name: string | null;
  executor_id: string | null;
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
// values fall through to a neutral muted style.
// Soft-tinted status pills used inside the shadcn `<Badge>` component.
// Just background + text — Badge keeps its default transparent border slot.
export function statusBadgeClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS")
    return "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-400";
  if (s === "ENQUEUED")
    return "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-400";
  if (s === "PENDING" || s === "DELAYED")
    return "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-400";
  if (s === "CANCELLED")
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400";
  if (s === "ERROR" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
    return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-400";
  return "bg-muted text-muted-foreground";
}

export function statusDotClass(status: string | null): string {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS") return "bg-green-500";
  if (s === "ENQUEUED") return "bg-violet-500";
  if (s === "PENDING" || s === "DELAYED") return "bg-blue-500";
  if (s === "CANCELLED") return "bg-amber-500";
  if (s === "ERROR" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED") return "bg-red-500";
  return "bg-muted-foreground/40";
}
