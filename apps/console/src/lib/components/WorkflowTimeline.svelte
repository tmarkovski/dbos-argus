<script lang="ts">
  import { Workflow as WorkflowIcon, Zap } from "@lucide/svelte";
  import prettyMs from "pretty-ms";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import type { FamilyWorkflow, FlowSelection, Step } from "./WorkflowFlow.svelte";
  import {
    buildTimeScale,
    buildTimelineRows,
    scaleTicks,
    stepSpan,
    workflowSpan,
    type Span,
    type TimelineRow,
  } from "$lib/timeline";
  import { statusDotClass } from "$lib/workflow-tree";

  let {
    family,
    steps,
    currentId,
    selection = null,
    onSelect,
  }: {
    family: FamilyWorkflow[];
    steps: Step[];
    currentId: string;
    selection?: FlowSelection;
    onSelect?: (sel: FlowSelection) => void;
  } = $props();

  let compress = $state(true);
  let now = $state(Date.now());
  let trackWidth = $state(0);

  const anyActive = $derived(
    family.some(
      (w) => w.status === "PENDING" || w.status === "ENQUEUED" || w.status === "DELAYED",
    ) || steps.some((s) => s.started_at && !s.completed_at),
  );

  $effect(() => {
    if (!anyActive) return;
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });

  const rows = $derived(buildTimelineRows(family, steps));
  const nameByWorkflowId = $derived(new Map(family.map((w) => [w.workflow_id, w.name ?? null])));

  // A wait parks the workflow (or blocks on another one); an instant op is a
  // point-in-time marker. Everything else is a regular executing step.
  function isWaitStep(s: Step): boolean {
    return (
      s.function_name === "DBOS.sleep" ||
      s.function_name === "DBOS.recv" ||
      s.function_name === "DBOS.getEvent" ||
      s.function_name === "DBOS.getResult"
    );
  }

  function isInstantStep(s: Step): boolean {
    return s.function_name === "DBOS.setEvent" || s.function_name === "DBOS.send";
  }

  type RowView = {
    row: TimelineRow;
    selectionId: string;
    // Bars in track coordinates; `queued` renders dashed before `bar`.
    bar: Span | null;
    queued: Span | null;
    barCls: string;
    isInstant: boolean;
    tooltip: string;
    durationLabel: string | null;
  };

  function fmtClock(t: number): string {
    return new Date(t).toLocaleString();
  }

  function tooltipFor(name: string, span: Span | null, extra: string | null): string {
    if (!span) return name;
    const range = `${fmtClock(span.start)} → ${span.openEnded ? "now" : fmtClock(span.end)}`;
    const dur = prettyMs(Math.max(0, span.end - span.start));
    return `${name}\n${range}\n${dur}${extra ? `\n${extra}` : ""}`;
  }

  function workflowBarCls(status: string | null): string {
    const s = (status ?? "").toUpperCase();
    if (s === "ERROR" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
      return "border border-status-error/70 bg-status-error/20";
    if (s === "CANCELLED") return "border border-status-warning/70 bg-status-warning/20";
    if (s === "PENDING" || s === "DELAYED")
      return "border border-status-running/70 bg-status-running/20 animate-pulse";
    if (s === "ENQUEUED") return "border border-dashed border-muted-foreground/60";
    return "border border-workflow-accent/70 bg-workflow-accent/20";
  }

  function stepBarCls(s: Step, span: Span | null): string {
    if (isInstantStep(s)) return "bg-status-warning dark:bg-highlight";
    if (isWaitStep(s)) {
      return span?.openEnded
        ? "border border-dashed border-status-running/80 animate-pulse"
        : "border border-dashed border-muted-foreground/50";
    }
    if (s.has_error) return "border border-status-error/70 bg-status-error/30";
    if (span?.openEnded) return "border border-status-running/70 bg-status-running/25 animate-pulse";
    return "border border-status-success/70 bg-status-success/25";
  }

  const rowViews: RowView[] = $derived.by(() => {
    const nowMs = now;
    // Per-workflow envelope over its steps. A recovered workflow's
    // started_at_epoch_ms is reset to the latest dequeue, which can land
    // *after* steps recorded by earlier attempts — the container bar must
    // still cover them.
    const envelopes = new Map<string, { min: number; max: number }>();
    for (const s of steps) {
      const span = stepSpan(s, nowMs);
      if (!span) continue;
      const env = envelopes.get(s.workflow_id);
      if (!env) {
        envelopes.set(s.workflow_id, { min: span.start, max: span.end });
      } else {
        env.min = Math.min(env.min, span.start);
        env.max = Math.max(env.max, span.end);
      }
    }
    return rows.map((r): RowView => {
      if (r.kind === "workflow") {
        const w = r.workflow as FamilyWorkflow;
        let span = workflowSpan(r.workflow, nowMs);
        const env = envelopes.get(w.workflow_id);
        if (span && env) {
          span = {
            start: Math.min(span.start, env.min),
            end: Math.max(span.end, env.max),
            openEnded: span.openEnded,
          };
        }
        // Dashed lead-in from the moment the parent enqueued the child to the
        // child's own run start. Only meaningful when the queue actually held
        // it back; sub-250ms queue time is noise at this scale.
        let queued: Span | null = null;
        const spawnStartRaw = r.spawnStep?.started_at;
        if (span && spawnStartRaw) {
          const spawnStart = Date.parse(spawnStartRaw);
          if (!Number.isNaN(spawnStart) && span.start - spawnStart > 250) {
            queued = { start: spawnStart, end: span.start, openEnded: false };
          }
        }
        const name = w.name ?? w.workflow_id;
        return {
          row: r,
          selectionId: `wf:${w.workflow_id}`,
          bar: span,
          queued,
          barCls: workflowBarCls(w.status),
          isInstant: false,
          tooltip: tooltipFor(name, span, w.status),
          durationLabel:
            w.status === "ENQUEUED"
              ? "queued"
              : span
                ? prettyMs(Math.max(0, span.end - span.start), { compact: true })
                : null,
        };
      }
      const s = r.step as Step;
      const span = stepSpan(r.step, nowMs);
      const displayMs =
        s.sleep_requested_ms != null
          ? s.sleep_requested_ms
          : span
            ? span.end - span.start
            : null;
      return {
        row: r,
        selectionId: `step:${s.workflow_id}:${s.function_id}`,
        bar: span,
        queued: null,
        barCls: stepBarCls(s, span),
        isInstant: isInstantStep(s),
        tooltip: tooltipFor(
          s.function_name,
          span,
          s.sleep_requested_ms != null
            ? `${prettyMs(s.sleep_requested_ms)} requested`
            : null,
        ),
        durationLabel:
          displayMs !== null && !isInstantStep(s)
            ? prettyMs(Math.max(0, displayMs), { compact: true })
            : null,
      };
    });
  });

  const scale = $derived.by(() => {
    const times: number[] = [];
    const protect: Array<{ start: number; end: number }> = [];
    for (const v of rowViews) {
      if (v.bar) times.push(v.bar.start, v.bar.end);
      if (v.queued) times.push(v.queued.start);
      // Executing steps anchor the compression cap and shield their span
      // from clamping; workflow containers and waits don't count as work.
      if (v.bar && v.row.kind === "step" && !isWaitStep(v.row.step as Step) && !v.isInstant) {
        protect.push({ start: v.bar.start, end: v.bar.end });
      }
    }
    return buildTimeScale(times, compress, protect);
  });

  const tickCount = $derived(
    trackWidth > 0 ? Math.max(2, Math.min(12, Math.floor(trackWidth / 110))) : 6,
  );
  const ticks = $derived(scale ? scaleTicks(scale, tickCount) : []);
  const breaks = $derived(scale ? scale.segments.filter((s) => s.compressed) : []);
  const nowX = $derived(anyActive && scale ? scale.toX(now) : null);

  function pct(x: number): string {
    return `${(x * 100).toFixed(4)}%`;
  }

  function barGeom(span: Span): string {
    if (!scale) return "";
    const left = scale.toX(span.start);
    const right = scale.toX(span.end);
    return `left: ${pct(left)}; width: ${pct(Math.max(0, right - left))};`;
  }

  function formatOffset(ms: number): string {
    if (ms <= 0) return "0s";
    return prettyMs(ms, { unitCount: 2, secondsDecimalDigits: ms < 10_000 ? 1 : 0 });
  }

  const selectedId = $derived.by(() => {
    if (!selection) return null;
    return selection.kind === "workflow"
      ? `wf:${selection.workflow.workflow_id}`
      : `step:${selection.step.workflow_id}:${selection.step.function_id}`;
  });

  // Clicking the already-selected row deselects (the timeline has no empty
  // canvas to click, unlike the graph pane).
  function select(v: RowView) {
    if (!onSelect) return;
    if (v.selectionId === selectedId) {
      onSelect(null);
      return;
    }
    const row = v.row;
    if (row.kind === "workflow") {
      const wfId = row.workflow.workflow_id;
      const wf = family.find((w) => w.workflow_id === wfId);
      if (wf) onSelect({ kind: "workflow", workflow: wf });
    } else {
      const { workflow_id, function_id } = row.step;
      const step = steps.find(
        (s) => s.workflow_id === workflow_id && s.function_id === function_id,
      );
      if (step) onSelect({ kind: "step", step });
    }
  }

  function stepName(s: Step): string {
    if (s.function_name === "DBOS.setEvent")
      return s.event_key ? `set → "${s.event_key}"` : "set → event";
    if (s.function_name === "DBOS.getEvent")
      return s.event_key ? `get ← "${s.event_key}"` : "get ← event";
    if (s.function_name === "DBOS.recv")
      return s.event_key ? `recv ← "${s.event_key}"` : "recv";
    if (s.function_name === "DBOS.getResult") {
      const awaited = s.child_workflow_id
        ? nameByWorkflowId.get(s.child_workflow_id)
        : null;
      return `← ${awaited ?? "getResult"}`;
    }
    if (s.function_name.startsWith("DBOS."))
      return s.function_name.slice("DBOS.".length);
    return s.function_name;
  }

  function stepNameCls(s: Step): string {
    if (isInstantStep(s) || s.function_name === "DBOS.getEvent" || s.function_name === "DBOS.recv")
      return "text-highlight-foreground dark:text-highlight";
    if (s.function_name === "DBOS.getResult") return "text-workflow-accent";
    if (s.function_name.startsWith("DBOS.")) return "text-muted-foreground";
    if (s.child_workflow_id) return "text-workflow-accent";
    return "text-foreground";
  }

  function stepDotCls(s: Step): string {
    if (s.function_name.startsWith("DBOS.")) return "bg-muted-foreground/40";
    if (s.has_error) return "bg-status-error";
    if (s.started_at && !s.completed_at) return "bg-status-running animate-pulse";
    if (s.completed_at) return "bg-status-success";
    return "bg-muted-foreground/40";
  }

  const BREAK_STRIPES =
    "repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in oklab, var(--color-muted-foreground) 20%, transparent) 5px 7px)";
</script>

<div class="bg-background relative flex h-full min-h-0 flex-col">
  {#if scale?.wouldCompress}
    <!-- right-14 clears the details pane's floating expand button (top-3
         right-3, 32px wide) when the pane is collapsed. -->
    <ToggleGroup.Root
      class="bg-card shadow-surface absolute top-3 right-14 z-10 rounded-lg"
      type="single"
      variant="outline"
      value={compress ? "compressed" : "linear"}
      onValueChange={(v) => {
        if (v) compress = v === "compressed";
      }}
    >
      <ToggleGroup.Item value="compressed" class="h-7 px-2.5">Compress waits</ToggleGroup.Item>
      <ToggleGroup.Item value="linear" class="h-7 px-2.5">True scale</ToggleGroup.Item>
    </ToggleGroup.Root>
  {/if}

  <!-- pt-12 keeps the axis clear of the page's floating Graph | Timeline
       toggle, which overlays the (empty) label-column corner. -->
  <div class="grid flex-none grid-cols-[280px_minmax(0,1fr)] pt-12 pr-6 pb-1">
    <div></div>
    <div class="relative h-5" bind:clientWidth={trackWidth}>
      {#each ticks as tick (tick.x)}
        <span
          class="text-muted-foreground absolute top-0 font-mono text-[10px] whitespace-nowrap {tick.x >
          0
            ? '-translate-x-1/2'
            : ''}"
          style="left: {pct(tick.x)}"
        >
          {formatOffset(tick.offsetMs)}
        </span>
      {/each}
      {#each breaks as brk (brk.x0)}
        <span
          class="text-muted-foreground absolute top-0 -translate-x-1/2 font-mono text-[10px]"
          style="left: {pct((brk.x0 + brk.x1) / 2)}"
          title="{prettyMs(brk.t1 - brk.t0)} compressed"
        >
          ⫽
        </span>
      {/each}
    </div>
  </div>

  <div class="min-h-0 flex-1 overflow-y-auto">
    <div class="relative min-h-full pb-6">
      {#if scale}
        <div
          aria-hidden="true"
          class="pointer-events-none absolute inset-0 grid grid-cols-[280px_minmax(0,1fr)] pr-6"
        >
          <div></div>
          <div class="relative">
            {#each ticks as tick (tick.x)}
              {#if tick.x > 0}
                <div class="bg-border/70 absolute inset-y-0 w-px" style="left: {pct(tick.x)}"></div>
              {/if}
            {/each}
            {#each breaks as brk (brk.x0)}
              <div
                class="absolute inset-y-0"
                style="left: {pct(brk.x0)}; width: {pct(
                  brk.x1 - brk.x0,
                )}; background: {BREAK_STRIPES};"
              ></div>
            {/each}
          </div>
        </div>
      {:else}
        <p class="text-muted-foreground px-4 py-2 text-xs">
          No step timing recorded — this database predates DBOS's step timestamps.
        </p>
      {/if}

      {#each rowViews as v (v.selectionId)}
        {@const isWorkflow = v.row.kind === "workflow"}
        {@const selected = v.selectionId === selectedId}
        <button
          type="button"
          class="grid w-full cursor-pointer grid-cols-[280px_minmax(0,1fr)] pr-6 text-left
            {isWorkflow ? 'h-8' : 'h-7'}
            {selected
            ? 'bg-primary/8 shadow-[inset_2px_0_0_var(--color-primary)]'
            : 'hover:bg-muted/60'}"
          title={v.tooltip}
          aria-pressed={selected}
          onclick={() => select(v)}
        >
          <span
            class="flex min-w-0 items-center gap-2"
            style="padding-left: {12 + v.row.depth * 14}px"
          >
            {#if v.row.kind === "workflow"}
              {@const w = v.row.workflow}
              <WorkflowIcon class="text-workflow-accent h-3 w-3 flex-none" aria-hidden="true" />
              <span
                class="truncate font-mono text-xs font-medium
                  {w.workflow_id === currentId ? 'text-workflow-accent' : 'text-foreground'}"
                title={w.workflow_id}
              >
                {w.name ?? w.workflow_id}
              </span>
              <span
                class="h-2 w-2 flex-none rounded-full {statusDotClass(w.status)}"
                aria-hidden="true"
              ></span>
            {:else}
              {@const s = v.row.step as Step}
              {#if isInstantStep(s)}
                <Zap
                  class="fill-status-warning text-status-warning dark:fill-highlight dark:text-highlight h-3 w-3 flex-none"
                  aria-hidden="true"
                />
              {:else}
                <span
                  class="h-2 w-2 flex-none rounded-full {stepDotCls(s)}"
                  aria-hidden="true"
                ></span>
              {/if}
              <span class="text-muted-foreground flex-none font-mono text-[10px]">
                #{s.function_id}
              </span>
              <span class="truncate font-mono text-xs {stepNameCls(s)}">{stepName(s)}</span>
            {/if}
            {#if v.durationLabel}
              <span class="text-muted-foreground ml-auto flex-none pr-3 font-mono text-[10px]">
                {v.durationLabel}
              </span>
            {/if}
          </span>
          <span class="relative block h-full">
            {#if scale && v.queued}
              <span
                class="border-muted-foreground/60 absolute top-1/2 h-3 min-w-[3px] -translate-y-1/2 rounded-[3px] border border-dashed"
                style={barGeom(v.queued)}
                aria-hidden="true"
              ></span>
            {/if}
            {#if scale && v.bar}
              <span
                class="absolute top-1/2 min-w-[3px] -translate-y-1/2 rounded-[3px]
                  {isWorkflow ? 'h-4' : 'h-3'}
                  {v.bar.openEnded ? 'rounded-r-none' : ''}
                  {v.barCls}"
                style={barGeom(v.bar)}
                aria-hidden="true"
              ></span>
            {/if}
          </span>
        </button>
      {/each}

      {#if nowX !== null}
        <div
          aria-hidden="true"
          class="pointer-events-none absolute inset-0 grid grid-cols-[280px_minmax(0,1fr)] pr-6"
        >
          <div></div>
          <div class="relative">
            <div class="bg-status-running/80 absolute inset-y-0 w-px" style="left: {pct(nowX)}"></div>
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
