<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import { Workflow, Zap } from "@lucide/svelte";
  import prettyMs from "pretty-ms";

  type StepKind = "step" | "child" | "system";
  type StepStatus = "error" | "running" | "success" | null;
  type EventDirection = "set" | "get" | null;

  type NodeData = {
    functionId: number;
    functionName: string;
    kind: StepKind;
    status: StepStatus;
    durationMs: number | null;
    awaitsWorkflowId?: string | null;
    awaitedWorkflowName?: string | null;
    spawnedWorkflowName?: string | null;
    eventDirection?: EventDirection;
    eventKey?: string | null;
    sleepRequestedMs?: number | null;
    startedAt?: string | null;
    isFirst?: boolean;
    isLast?: boolean;
  };

  let { data, selected }: NodeProps & { data: NodeData } = $props();

  const dotClass = $derived.by(() => {
    if (data.kind === "system") return "bg-muted-foreground/40";
    switch (data.status) {
      case "error":
        return "bg-status-error";
      case "running":
        return "bg-status-running animate-pulse";
      case "success":
        return "bg-status-success";
      default:
        return "bg-muted-foreground/40";
    }
  });

  const nameClass = $derived.by(() => {
    if (data.kind === "child") return "text-workflow-accent";
    if (data.kind === "system") return "text-muted-foreground";
    return "";
  });

  function formatDuration(ms: number): string {
    // Compact like "450ms", "1.5s", "2m 30s", "24h", "1d". `compact: true`
    // keeps it to a single largest unit which fits the tight node label.
    return prettyMs(ms, { compact: true });
  }

  // Sleep steps display the originally requested duration (the "timeout") in
  // place of wall-clock elapsed — for in-progress sleeps wall-clock is null
  // and for completed sleeps it just duplicates the requested value.
  const displayDurationMs = $derived(
    data.sleepRequestedMs != null ? data.sleepRequestedMs : data.durationMs,
  );

  let now = $state(Date.now());

  // DBOS writes the sleep row with both started_at and completed_at as soon
  // as it's encountered — the wake-up time is stored in `output` and the
  // workflow is parked outside of step-tracking until then. So step status
  // is always "success" for a sleep; "currently sleeping" means: this row is
  // DBOS.sleep, it's the workflow's last step, and the wake-up time is still
  // in the future.
  const wakeMs = $derived.by(() => {
    if (data.functionName !== "DBOS.sleep") return null;
    if (data.sleepRequestedMs == null || data.sleepRequestedMs <= 0) return null;
    if (!data.startedAt) return null;
    if (data.isLast !== true) return null;
    return new Date(data.startedAt).getTime() + data.sleepRequestedMs;
  });

  // Countdown ring only appears in the final minute (per spec). Above 1m, the
  // ring would move imperceptibly anyway, so we render the static total like
  // any other sleep step. The ring fills against a 60s window — not the
  // original requested sleep — so a 60s remaining means empty and 0s means
  // full regardless of whether the workflow was sleeping for 2m or 2h.
  const RING_WINDOW_MS = 60_000;
  const ringState = $derived.by(() => {
    if (wakeMs == null) return null;
    const remaining = wakeMs - now;
    if (remaining <= 0 || remaining >= RING_WINDOW_MS) return null;
    const ratio = Math.min(1, Math.max(0, (RING_WINDOW_MS - remaining) / RING_WINDOW_MS));
    const seconds = Math.max(0, Math.ceil(remaining / 1000));
    return { remaining, ratio, seconds };
  });

  $effect(() => {
    if (wakeMs == null) return;
    const wake = wakeMs;

    let timerId: ReturnType<typeof setTimeout> | null = null;
    let frameId: number | null = null;

    const tick = () => {
      now = Date.now();
      const remaining = wake - now;
      if (remaining <= 0) return;
      if (remaining < 60_000) {
        // In the final minute: rAF for smooth fill + per-second number update.
        frameId = requestAnimationFrame(tick);
      } else {
        // Otherwise sleep until we cross into the final-minute window. One
        // timer total, not one per second — cheap for long sleeps.
        timerId = setTimeout(tick, remaining - 60_000 + 50);
      }
    };
    tick();

    return () => {
      if (timerId !== null) clearTimeout(timerId);
      if (frameId !== null) cancelAnimationFrame(frameId);
    };
  });

  const RING_RADIUS = 11;
  const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
</script>

<div
  class="flex h-full w-full cursor-pointer items-center gap-2 rounded-md border px-3 py-1
    {selected
      ? 'border-primary bg-primary/5'
      : 'border-border hover:bg-muted/40'}"
>
  {#if !data.isFirst}
    <Handle type="target" position={Position.Top} isConnectable={false} />
  {/if}
  {#if data.eventDirection}
    <Zap
      class="fill-status-warning text-status-warning dark:fill-highlight dark:text-highlight h-3 w-3 flex-none"
      aria-hidden="true"
    />
  {:else if data.kind === "child"}
    <Workflow class="text-workflow-accent h-3 w-3 flex-none" aria-hidden="true" />
  {:else}
    <span class="h-2 w-2 flex-none rounded-full {dotClass}" aria-hidden="true"></span>
  {/if}
  <span class="text-muted-foreground flex-none font-mono text-[10px]">#{data.functionId}</span>
  {#if data.eventDirection}
    <span class="truncate font-mono text-xs" title={data.functionName}>
      <span class="text-highlight-foreground dark:text-highlight">{data.eventDirection}</span>
      <span class="text-muted-foreground">
        {data.eventDirection === "set" ? "→" : "←"}
      </span>
      {#if data.eventKey}
        <span class="text-foreground">"{data.eventKey}"</span>
      {:else}
        <span class="text-muted-foreground">event</span>
      {/if}
    </span>
  {:else if data.awaitedWorkflowName}
    <span class="text-workflow-accent truncate font-mono text-xs" title={data.functionName}>
      {data.awaitedWorkflowName}
    </span>
  {:else if data.spawnedWorkflowName}
    <span class="text-workflow-accent truncate font-mono text-xs" title={data.functionName}>
      {data.spawnedWorkflowName}
    </span>
  {:else}
    <span class="truncate font-mono text-xs {nameClass}" title={data.functionName}>
      {data.kind === "system" && data.functionName.startsWith("DBOS.")
        ? data.functionName.slice("DBOS.".length)
        : data.functionName}
    </span>
  {/if}
  {#if ringState}
    <span
      class="text-status-running ml-auto -mr-2 flex flex-none items-center"
      title="Sleep — {ringState.seconds}s remaining"
    >
      <span class="relative inline-flex h-6 w-6 items-center justify-center">
        <svg
          class="absolute inset-0 h-full w-full"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            cx="12"
            cy="12"
            r={RING_RADIUS}
            fill="none"
            stroke="currentColor"
            stroke-opacity="0.25"
            stroke-width="1.5"
          />
          <circle
            cx="12"
            cy="12"
            r={RING_RADIUS}
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-dasharray={RING_CIRCUMFERENCE}
            stroke-dashoffset={RING_CIRCUMFERENCE * (1 - ringState.ratio)}
            transform="rotate(-90 12 12)"
          />
        </svg>
        <span class="relative font-mono text-[9px] leading-none tabular-nums">
          {ringState.seconds}s
        </span>
      </span>
    </span>
  {:else if data.awaitedWorkflowName || data.spawnedWorkflowName || displayDurationMs !== null}
    <span
      class="text-muted-foreground ml-auto flex flex-none items-center gap-1 font-mono text-[10px]"
    >
      {#if data.spawnedWorkflowName}
        <span aria-hidden="true">→</span>
      {:else if data.awaitedWorkflowName}
        <span aria-hidden="true">←</span>
      {/if}
      {#if displayDurationMs !== null}
        <span>{formatDuration(displayDurationMs)}</span>
      {/if}
    </span>
  {/if}
  {#if !data.isLast}
    <Handle type="source" position={Position.Bottom} isConnectable={false} />
  {/if}
  {#if data.kind === "child"}
    <Handle id="spawn" type="source" position={Position.Right} isConnectable={false} />
  {/if}
  {#if data.awaitsWorkflowId}
    <Handle id="return" type="target" position={Position.Right} isConnectable={false} />
  {/if}
</div>
