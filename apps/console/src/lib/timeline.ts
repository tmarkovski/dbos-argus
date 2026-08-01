// Pure logic for the workflow timeline (waterfall) view: row ordering,
// per-row time spans, and the piecewise-linear time scale with optional
// wait compression. Kept free of Svelte imports so it unit-tests directly.
//
// The types below are structural subsets of `FamilyWorkflow` / `Step` from
// WorkflowFlow.svelte — declared here (rather than imported) so this module
// doesn't depend on a .svelte file and stays loadable from plain vitest.

export type TimelineWorkflow = {
  workflow_id: string;
  parent_workflow_id: string | null;
  name: string | null;
  status: string | null;
  // COALESCE(started_at_epoch_ms, created_at) server-side: run start when the
  // workflow has begun executing, enqueue time while it's still ENQUEUED.
  started_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type TimelineStep = {
  workflow_id: string;
  function_id: number;
  function_name: string;
  has_error: boolean;
  child_workflow_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  event_key: string | null;
  sleep_requested_ms: number | null;
};

export type TimelineRow =
  | {
      kind: "workflow";
      workflow: TimelineWorkflow;
      // The parent step that spawned this workflow (null for the root). Its
      // started_at marks the enqueue moment, which is what lets the view
      // draw a queued segment before the child's own run start.
      spawnStep: TimelineStep | null;
      depth: number;
    }
  | { kind: "step"; step: TimelineStep; depth: number };

// Trace ordering: each workflow emits a header row followed by its steps in
// function_id order; a step that spawned a family child is replaced by that
// child's entire subtree (the child's header row *is* the spawn step). This
// mirrors the DFS the family list arrives in while interleaving children at
// the exact call site instead of appending them after the parent's steps.
export function buildTimelineRows(
  family: TimelineWorkflow[],
  steps: TimelineStep[],
): TimelineRow[] {
  const byId = new Map(family.map((w) => [w.workflow_id, w]));
  const stepsByWf = new Map<string, TimelineStep[]>();
  for (const s of steps) {
    const list = stepsByWf.get(s.workflow_id) ?? [];
    list.push(s);
    stepsByWf.set(s.workflow_id, list);
  }
  for (const list of stepsByWf.values()) {
    list.sort((a, b) => a.function_id - b.function_id);
  }

  const rows: TimelineRow[] = [];
  const visited = new Set<string>();

  function emit(wf: TimelineWorkflow, spawnStep: TimelineStep | null, depth: number) {
    if (visited.has(wf.workflow_id)) return;
    visited.add(wf.workflow_id);
    rows.push({ kind: "workflow", workflow: wf, spawnStep, depth });
    for (const s of stepsByWf.get(wf.workflow_id) ?? []) {
      const child =
        s.child_workflow_id && !s.function_name.startsWith("DBOS.")
          ? byId.get(s.child_workflow_id)
          : undefined;
      if (child && !visited.has(child.workflow_id)) {
        emit(child, s, depth + 1);
      } else {
        rows.push({ kind: "step", step: s, depth: depth + 1 });
      }
    }
  }

  for (const w of family) {
    if (!w.parent_workflow_id || !byId.has(w.parent_workflow_id)) emit(w, null, 0);
  }
  // Family members whose spawn step hasn't been walked (defensive — a spawn
  // op row should always exist once the child does).
  for (const w of family) {
    if (!visited.has(w.workflow_id)) emit(w, null, 0);
  }
  return rows;
}

export type Span = { start: number; end: number; openEnded: boolean };

const TERMINAL_STATUSES = new Set([
  "SUCCESS",
  "ERROR",
  "CANCELLED",
  "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
]);

// DBOS writes the operation_outputs row only when a step finishes, with one
// exception: sleeps are recorded up-front with started ≈ completed and the
// wake-up encoded in the output (surfaced as sleep_requested_ms). So a
// sleep's true extent is start → start+requested, clamped to `now` while the
// workflow is still parked.
//
// `workflowEnd` is the owning workflow's terminal completion time (null while
// it's still running). Inferred extents — a sleep's projected wake, an
// open-ended stretch to `now` — are clamped to it so a workflow cancelled
// mid-sleep doesn't render the sleep running to term (or still pulsing) after
// the workflow is dead. Recorded completed_at timestamps are facts and are
// never clamped.
export function stepSpan(
  s: TimelineStep,
  now: number,
  workflowEnd: number | null = null,
): Span | null {
  if (!s.started_at) return null;
  const start = Date.parse(s.started_at);
  if (Number.isNaN(start)) return null;
  const clamp = (span: Span): Span =>
    workflowEnd !== null && span.end > workflowEnd
      ? { start: span.start, end: Math.max(workflowEnd, span.start), openEnded: false }
      : span;
  if (s.function_name === "DBOS.sleep" && s.sleep_requested_ms != null) {
    const wake = start + s.sleep_requested_ms;
    if (wake > now) return clamp({ start, end: Math.max(now, start), openEnded: true });
    return clamp({ start, end: wake, openEnded: false });
  }
  if (s.completed_at) {
    const end = Date.parse(s.completed_at);
    if (!Number.isNaN(end)) return { start, end: Math.max(end, start), openEnded: false };
  }
  return clamp({ start, end: Math.max(now, start), openEnded: true });
}

export function workflowSpan(w: TimelineWorkflow, now: number): Span | null {
  const start = Date.parse(w.started_at);
  if (Number.isNaN(start)) return null;
  if (w.completed_at) {
    const end = Date.parse(w.completed_at);
    if (!Number.isNaN(end)) return { start, end: Math.max(end, start), openEnded: false };
  }
  if (TERMINAL_STATUSES.has(w.status ?? "")) {
    // Terminal but no completed_at (data recorded by an older DBOS): fall
    // back to updated_at rather than extending the bar to `now` forever.
    const end = Date.parse(w.updated_at);
    return { start, end: Number.isNaN(end) ? start : Math.max(end, start), openEnded: false };
  }
  return { start, end: Math.max(now, start), openEnded: true };
}

export type ScaleSegment = {
  t0: number;
  t1: number;
  x0: number;
  x1: number;
  compressed: boolean;
};

export type TimeScale = {
  min: number;
  max: number;
  segments: ScaleSegment[];
  // True when compression is on *and* at least one segment got clamped.
  compressionApplied: boolean;
  // True when compression would clamp something — drives the toggle's
  // visibility independent of its current state.
  wouldCompress: boolean;
  toX(t: number): number;
  fromX(x: number): number;
};

// A wait is "long" when it exceeds this multiple of the median executing-step
// duration. 10x keeps ordinary traces (steps within one order of magnitude)
// fully linear while a 14-day sleep next to 1s steps clamps hard. Once a
// wait *is* clamped, it renders at the median itself (threshold / 10) — about
// one typical step wide — so the reclaimed width goes to the actual work
// instead of a big hatched band.
const COMPRESS_MEDIAN_FACTOR = 10;
const MIN_CAP_MS = 1_000;

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

// Piecewise-linear time → [0, 1] mapping. `times` are every bar boundary in
// the view; the axis is linear within each inter-boundary segment. With
// `compress`, segments longer than the cap contribute only the cap's worth
// of width — since bar edges always sit on boundaries, every bar shrinks or
// shifts consistently and nothing overlaps.
//
// `protect` marks intervals where a step was actually executing. They set
// the cap (10x their median duration) and are exempt from clamping — the
// view is called "compress waits", and squeezing a genuinely long step under
// a hatched band would misread as idle time. Without any protected interval
// (e.g. a family that only slept) the cap falls back to the median gap.
export function buildTimeScale(
  times: number[],
  compress: boolean,
  protect: Array<{ start: number; end: number }> = [],
): TimeScale | null {
  const uniq = [...new Set(times.filter((t) => Number.isFinite(t)))].sort((a, b) => a - b);
  if (uniq.length < 2) return null;

  const gaps: number[] = [];
  for (let i = 1; i < uniq.length; i++) gaps.push(uniq[i] - uniq[i - 1]);
  const protectDurations = protect
    .map((p) => p.end - p.start)
    .filter((d) => Number.isFinite(d) && d > 0);
  const base = median(protectDurations) ?? median(gaps)!;
  const cap = Math.max(base * COMPRESS_MEDIAN_FACTOR, MIN_CAP_MS);

  function isProtected(t0: number, t1: number): boolean {
    return protect.some((p) => p.start < t1 && p.end > t0);
  }

  const clampable = gaps.map(
    (g, i) => g > cap && !isProtected(uniq[i], uniq[i + 1]),
  );
  const wouldCompress = clampable.some(Boolean);

  const clampWeight = cap / COMPRESS_MEDIAN_FACTOR;
  const weights = gaps.map((g, i) => (compress && clampable[i] ? clampWeight : g));
  const total = weights.reduce((a, b) => a + b, 0);

  const segments: ScaleSegment[] = [];
  let acc = 0;
  for (let i = 0; i < gaps.length; i++) {
    const x0 = acc / total;
    acc += weights[i];
    segments.push({
      t0: uniq[i],
      t1: uniq[i + 1],
      x0,
      x1: acc / total,
      compressed: compress && clampable[i],
    });
  }

  const min = uniq[0];
  const max = uniq[uniq.length - 1];

  function toX(t: number): number {
    if (t <= min) return 0;
    if (t >= max) return 1;
    const seg = segments.find((s) => t <= s.t1)!;
    return seg.x0 + ((t - seg.t0) / (seg.t1 - seg.t0)) * (seg.x1 - seg.x0);
  }

  function fromX(x: number): number {
    if (x <= 0) return min;
    if (x >= 1) return max;
    const seg = segments.find((s) => x <= s.x1)!;
    return seg.t0 + ((x - seg.x0) / (seg.x1 - seg.x0)) * (seg.t1 - seg.t0);
  }

  return {
    min,
    max,
    segments,
    compressionApplied: compress && wouldCompress,
    wouldCompress,
    toX,
    fromX,
  };
}

export type Tick = { x: number; offsetMs: number };

// Evenly spaced ticks in *visual* space, mapped back to time. Ticks landing
// strictly inside a compressed segment are dropped — the time there is
// distorted by design and the break band already marks it. Each compressed
// segment instead contributes a tick at its end, so the axis re-anchors
// where real time resumes after a break.
export function scaleTicks(scale: TimeScale, count: number): Tick[] {
  const minGap = 0.5 / count;
  const ticks: Tick[] = [];
  for (const s of scale.segments) {
    if (s.compressed && s.x1 < 0.98) {
      ticks.push({ x: s.x1, offsetMs: s.t1 - scale.min });
    }
  }
  for (let i = 0; i < count; i++) {
    const x = i / count;
    const inCompressed = scale.segments.some(
      (s) => s.compressed && x > s.x0 && x < s.x1,
    );
    if (inCompressed) continue;
    // Break anchors win over even ticks when they'd crowd each other.
    if (ticks.some((t) => Math.abs(t.x - x) < minGap)) continue;
    ticks.push({ x, offsetMs: scale.fromX(x) - scale.min });
  }
  return ticks.sort((a, b) => a.x - b.x);
}
