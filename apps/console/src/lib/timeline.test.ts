import { describe, expect, it } from "vitest";
import {
  buildTimeScale,
  buildTimelineRows,
  scaleTicks,
  stepSpan,
  workflowSpan,
  type TimelineStep,
  type TimelineWorkflow,
} from "./timeline";

const T0 = Date.parse("2026-01-01T00:00:00Z");

function iso(offsetMs: number): string {
  return new Date(T0 + offsetMs).toISOString();
}

function wf(over: Partial<TimelineWorkflow> & { workflow_id: string }): TimelineWorkflow {
  return {
    parent_workflow_id: null,
    name: over.workflow_id,
    status: "SUCCESS",
    started_at: iso(0),
    updated_at: iso(1000),
    completed_at: iso(1000),
    ...over,
  };
}

function step(over: Partial<TimelineStep> & { workflow_id: string; function_id: number }): TimelineStep {
  return {
    function_name: "do_thing",
    has_error: false,
    has_output: false,
    child_workflow_id: null,
    started_at: iso(0),
    completed_at: iso(100),
    event_key: null,
    sleep_requested_ms: null,
    ...over,
  };
}

describe("buildTimelineRows", () => {
  it("interleaves a spawned child subtree at its call site", () => {
    const family = [
      wf({ workflow_id: "root" }),
      wf({ workflow_id: "child", parent_workflow_id: "root" }),
    ];
    const steps = [
      step({ workflow_id: "root", function_id: 0, function_name: "before" }),
      step({
        workflow_id: "root",
        function_id: 1,
        function_name: "child_wf",
        child_workflow_id: "child",
      }),
      step({ workflow_id: "root", function_id: 2, function_name: "after" }),
      step({ workflow_id: "child", function_id: 0, function_name: "inner" }),
    ];
    const rows = buildTimelineRows(family, steps);
    const labels = rows.map((r) =>
      r.kind === "workflow" ? `wf:${r.workflow.workflow_id}` : `step:${r.step.function_name}`,
    );
    expect(labels).toEqual([
      "wf:root",
      "step:before",
      "wf:child",
      "step:inner",
      "step:after",
    ]);
    const childRow = rows[2];
    expect(childRow.kind === "workflow" && childRow.spawnStep?.function_id).toBe(1);
    expect(childRow.kind === "workflow" && childRow.depth).toBe(1);
  });

  it("keeps DBOS.getResult rows as plain steps even with a child id", () => {
    const family = [
      wf({ workflow_id: "root" }),
      wf({ workflow_id: "child", parent_workflow_id: "root" }),
    ];
    const steps = [
      step({
        workflow_id: "root",
        function_id: 0,
        function_name: "child_wf",
        child_workflow_id: "child",
      }),
      step({
        workflow_id: "root",
        function_id: 1,
        function_name: "DBOS.getResult",
        child_workflow_id: "child",
      }),
    ];
    const rows = buildTimelineRows(family, steps);
    expect(rows.map((r) => r.kind)).toEqual(["workflow", "workflow", "step"]);
  });

  it("keeps a selectable row for a spawn step with an error or payload", () => {
    const family = [
      wf({ workflow_id: "root" }),
      wf({ workflow_id: "child", parent_workflow_id: "root" }),
    ];
    const steps = [
      step({
        workflow_id: "root",
        function_id: 0,
        function_name: "child_wf",
        child_workflow_id: "child",
        has_error: true,
      }),
    ];
    const rows = buildTimelineRows(family, steps);
    const labels = rows.map((r) =>
      r.kind === "workflow" ? `wf:${r.workflow.workflow_id}` : `step:${r.step.function_id}`,
    );
    // The errored spawn keeps its own row ahead of the child subtree.
    expect(labels).toEqual(["wf:root", "step:0", "wf:child"]);
  });

  it("degrades a second spawn of the same child to a plain step row", () => {
    const family = [
      wf({ workflow_id: "root" }),
      wf({ workflow_id: "child", parent_workflow_id: "root" }),
    ];
    const steps = [
      step({
        workflow_id: "root",
        function_id: 0,
        function_name: "child_wf",
        child_workflow_id: "child",
      }),
      step({
        workflow_id: "root",
        function_id: 1,
        function_name: "child_wf",
        child_workflow_id: "child",
      }),
    ];
    const rows = buildTimelineRows(family, steps);
    const labels = rows.map((r) =>
      r.kind === "workflow" ? `wf:${r.workflow.workflow_id}` : `step:${r.step.function_id}`,
    );
    expect(labels).toEqual(["wf:root", "wf:child", "step:1"]);
  });

  it("terminates on parent-pointer cycles", () => {
    const family = [
      wf({ workflow_id: "a", parent_workflow_id: "b" }),
      wf({ workflow_id: "b", parent_workflow_id: "a" }),
    ];
    const rows = buildTimelineRows(family, []);
    expect(rows.map((r) => r.kind === "workflow" && r.workflow.workflow_id)).toEqual(["a", "b"]);
  });

  it("emits unlinked family members instead of dropping them", () => {
    const family = [
      wf({ workflow_id: "root" }),
      wf({ workflow_id: "orphan", parent_workflow_id: "root" }),
    ];
    const rows = buildTimelineRows(family, []);
    expect(rows.map((r) => r.kind === "workflow" && r.workflow.workflow_id)).toEqual([
      "root",
      "orphan",
    ]);
  });
});

describe("spans", () => {
  const now = T0 + 60_000;

  it("uses recorded start/complete for ordinary steps", () => {
    const s = step({ workflow_id: "w", function_id: 0 });
    expect(stepSpan(s, now)).toEqual({ start: T0, end: T0 + 100, openEnded: false });
  });

  it("extends a started-but-uncompleted step to now", () => {
    const s = step({ workflow_id: "w", function_id: 0, completed_at: null });
    expect(stepSpan(s, now)).toEqual({ start: T0, end: now, openEnded: true });
  });

  it("returns null without a start time", () => {
    expect(stepSpan(step({ workflow_id: "w", function_id: 0, started_at: null }), now)).toBeNull();
  });

  it("treats a sleep without sleep_requested_ms like an ordinary step", () => {
    const s = step({
      workflow_id: "w",
      function_id: 0,
      function_name: "DBOS.sleep",
      completed_at: iso(5),
      sleep_requested_ms: null,
    });
    expect(stepSpan(s, now)).toEqual({ start: T0, end: T0 + 5, openEnded: false });
  });

  it("spans a sleep to its wake-up, not its recorded completion", () => {
    const s = step({
      workflow_id: "w",
      function_id: 0,
      function_name: "DBOS.sleep",
      completed_at: iso(5), // DBOS records sleeps up-front: completed ≈ started
      sleep_requested_ms: 30_000,
    });
    expect(stepSpan(s, now)).toEqual({ start: T0, end: T0 + 30_000, openEnded: false });
  });

  it("clamps an in-progress sleep to now", () => {
    const s = step({
      workflow_id: "w",
      function_id: 0,
      function_name: "DBOS.sleep",
      completed_at: iso(5),
      sleep_requested_ms: 600_000,
    });
    expect(stepSpan(s, now)).toEqual({ start: T0, end: now, openEnded: true });
  });

  it("clamps a sleep's projected wake to the workflow's terminal end", () => {
    // 1h sleep, workflow cancelled 5s in: the bar must stop at the death,
    // not run to term.
    const s = step({
      workflow_id: "w",
      function_id: 0,
      function_name: "DBOS.sleep",
      completed_at: iso(5),
      sleep_requested_ms: 3_600_000,
    });
    const viewedAt = T0 + 7_200_000;
    expect(stepSpan(s, viewedAt, T0 + 5000)).toEqual({
      start: T0,
      end: T0 + 5000,
      openEnded: false,
    });
    // Viewed while the wake is still in the future: same clamp, and the bar
    // must not read as "still sleeping" on a dead workflow.
    expect(stepSpan(s, T0 + 60_000, T0 + 5000)).toEqual({
      start: T0,
      end: T0 + 5000,
      openEnded: false,
    });
  });

  it("clamps an open-ended step to the workflow's terminal end", () => {
    const s = step({ workflow_id: "w", function_id: 0, completed_at: null });
    expect(stepSpan(s, now, T0 + 2000)).toEqual({
      start: T0,
      end: T0 + 2000,
      openEnded: false,
    });
  });

  it("never clamps a recorded completion", () => {
    // completed_at is a fact; a workflow updated_at that sorts earlier
    // (clock write order) must not truncate it.
    const s = step({ workflow_id: "w", function_id: 0, completed_at: iso(3000) });
    expect(stepSpan(s, now, T0 + 1000)).toEqual({
      start: T0,
      end: T0 + 3000,
      openEnded: false,
    });
  });

  it("ends a terminal workflow without completed_at at updated_at", () => {
    const w = wf({ workflow_id: "w", completed_at: null, updated_at: iso(2000) });
    expect(workflowSpan(w, now)).toEqual({ start: T0, end: T0 + 2000, openEnded: false });
  });

  it("extends a running workflow to now", () => {
    const w = wf({ workflow_id: "w", status: "PENDING", completed_at: null });
    expect(workflowSpan(w, now)).toEqual({ start: T0, end: now, openEnded: true });
  });
});

describe("buildTimeScale", () => {
  it("is linear when gaps are comparable", () => {
    const scale = buildTimeScale([0, 1000, 2000, 3000, 4000], true)!;
    expect(scale.wouldCompress).toBe(false);
    expect(scale.compressionApplied).toBe(false);
    expect(scale.toX(2000)).toBeCloseTo(0.5);
    expect(scale.fromX(0.25)).toBeCloseTo(1000);
  });

  it("clamps a dominant gap when compression is on", () => {
    // Four 1s gaps and one 100s gap. Linear puts the wait at ~96% of the
    // width; compressed renders it at the median-gap weight (1s) → 1/5.
    const times = [0, 1000, 2000, 3000, 4000, 104_000];
    const compressed = buildTimeScale(times, true)!;
    expect(compressed.wouldCompress).toBe(true);
    expect(compressed.compressionApplied).toBe(true);
    const waitSeg = compressed.segments[compressed.segments.length - 1];
    expect(waitSeg.compressed).toBe(true);
    expect(waitSeg.x1 - waitSeg.x0).toBeCloseTo(1 / 5);

    const linear = buildTimeScale(times, false)!;
    expect(linear.compressionApplied).toBe(false);
    expect(linear.wouldCompress).toBe(true);
    const linearWait = linear.segments[linear.segments.length - 1];
    expect(linearWait.x1 - linearWait.x0).toBeCloseTo(100 / 104);
  });

  it("round-trips toX/fromX inside uncompressed segments", () => {
    const scale = buildTimeScale([0, 1000, 2000, 3000, 4000, 104_000], true)!;
    for (const t of [500, 1500, 3500]) {
      expect(scale.fromX(scale.toX(t))).toBeCloseTo(t);
    }
  });

  it("clamps out-of-range inputs", () => {
    const scale = buildTimeScale([1000, 2000], false)!;
    expect(scale.toX(0)).toBe(0);
    expect(scale.toX(5000)).toBe(1);
    expect(scale.fromX(-1)).toBe(1000);
    expect(scale.fromX(2)).toBe(2000);
  });

  it("never compresses a span covered by an executing step", () => {
    // Same shape as the dominant-gap case, but the 100s stretch is a real
    // step's execution, not a wait — it must stay linear and unclamped.
    const times = [0, 1000, 2000, 3000, 4000, 104_000];
    const scale = buildTimeScale(times, true, [{ start: 4000, end: 104_000 }])!;
    expect(scale.wouldCompress).toBe(false);
    expect(scale.segments.every((s) => !s.compressed)).toBe(true);
    const seg = scale.segments[scale.segments.length - 1];
    expect(seg.x1 - seg.x0).toBeCloseTo(100 / 104);
  });

  it("derives the cap from executing-step durations, not boundary gaps", () => {
    // Boundaries 1ms apart would give a tiny median gap; the 2s executing
    // steps push the cap to 20s so the 15s wait survives uncompressed.
    const times = [0, 1, 2000, 2001, 4000, 19_000];
    const scale = buildTimeScale(times, true, [
      { start: 1, end: 2000 },
      { start: 2001, end: 4000 },
    ])!;
    expect(scale.wouldCompress).toBe(false);
  });

  it("returns null for degenerate inputs", () => {
    expect(buildTimeScale([], true)).toBeNull();
    expect(buildTimeScale([1000], true)).toBeNull();
    expect(buildTimeScale([1000, 1000], true)).toBeNull();
  });
});

describe("scaleTicks", () => {
  it("skips ticks inside compressed segments", () => {
    const scale = buildTimeScale([0, 1000, 2000, 3000, 4000, 104_000], true)!;
    const ticks = scaleTicks(scale, 10);
    // The compressed wait occupies the last 10/14 ≈ 71% of the axis; only
    // ticks in the leading linear region (plus x=0) survive.
    expect(ticks.length).toBeGreaterThan(0);
    expect(ticks[0]).toEqual({ x: 0, offsetMs: 0 });
    const waitSeg = scale.segments[scale.segments.length - 1];
    for (const tick of ticks) {
      expect(tick.x > waitSeg.x0 && tick.x < waitSeg.x1).toBe(false);
    }
  });

  it("covers the full axis when linear", () => {
    const scale = buildTimeScale([0, 10_000], false)!;
    const ticks = scaleTicks(scale, 5);
    expect(ticks.map((t) => t.offsetMs)).toEqual([0, 2000, 4000, 6000, 8000]);
  });

  it("anchors a tick at the end of a mid-scale break", () => {
    // 4x 1s gaps, a 100s wait, 4x 1s gaps. The wait clamps to the 1s median
    // weight, so its end sits at x = 5/9 with real time resuming at 104s.
    const times = [0, 1000, 2000, 3000, 4000, 104_000, 105_000, 106_000, 107_000, 108_000];
    const scale = buildTimeScale(times, true)!;
    const ticks = scaleTicks(scale, 9);
    const anchor = ticks.find((t) => Math.abs(t.x - 5 / 9) < 1e-9);
    expect(anchor).toBeDefined();
    expect(anchor!.offsetMs).toBe(104_000);
  });

  it("dedupes break anchors that crowd each other", () => {
    // Two 100s waits separated by only 100ms. Both clamp to the 1s weight;
    // with a coarse tick budget their anchors fall within minGap and only
    // the first survives.
    const times = [0, 1000, 2000, 3000, 4000, 104_000, 104_100, 204_100, 205_100, 206_100];
    const scale = buildTimeScale(times, true)!;
    const compressed = scale.segments.filter((s) => s.compressed);
    expect(compressed.length).toBe(2);
    const ticks = scaleTicks(scale, 3);
    const anchors = ticks.filter((t) =>
      compressed.some((s) => Math.abs(s.x1 - t.x) < 1e-9),
    );
    expect(anchors.length).toBe(1);
  });
});
