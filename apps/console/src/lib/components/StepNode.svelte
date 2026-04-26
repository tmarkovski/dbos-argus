<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import { Zap } from "@lucide/svelte";
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
    eventDirection?: EventDirection;
    eventKey?: string | null;
    sleepRequestedMs?: number | null;
    isFirst?: boolean;
    isLast?: boolean;
  };

  let { data, selected }: NodeProps & { data: NodeData } = $props();

  const dotClass = $derived.by(() => {
    if (data.kind === "child") return "bg-indigo-500";
    if (data.kind === "system") return "bg-muted-foreground/40";
    switch (data.status) {
      case "error":
        return "bg-red-500";
      case "running":
        return "bg-blue-500 animate-pulse";
      case "success":
        return "bg-green-500";
      default:
        return "bg-muted-foreground/40";
    }
  });

  const nameClass = $derived.by(() => {
    if (data.kind === "child") return "text-indigo-700 dark:text-indigo-400";
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
</script>

<div
  class="bg-background flex h-full w-full cursor-pointer items-center gap-2 rounded-md border border-foreground/20 px-2.5 py-1
    {selected ? 'ring-primary ring-2 border-primary' : ''}"
>
  {#if !data.isFirst}
    <Handle type="target" position={Position.Top} isConnectable={false} />
  {/if}
  {#if data.eventDirection}
    <Zap
      class="h-3 w-3 flex-none fill-yellow-400 text-yellow-500 dark:fill-yellow-300 dark:text-yellow-400"
      aria-hidden="true"
    />
  {:else}
    <span class="h-2 w-2 flex-none rounded-full {dotClass}" aria-hidden="true"></span>
  {/if}
  <span class="text-muted-foreground flex-none font-mono text-[10px]">#{data.functionId}</span>
  {#if data.eventDirection}
    <span class="truncate font-mono text-xs" title={data.functionName}>
      <span class="text-yellow-700 dark:text-yellow-400">{data.eventDirection}</span>
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
    <span class="truncate font-mono text-xs" title={data.functionName}>
      <span class="text-muted-foreground">result</span>
      <span class="text-muted-foreground">←</span>
      <span class="text-indigo-700 dark:text-indigo-400">{data.awaitedWorkflowName}</span>
    </span>
  {:else}
    <span class="truncate font-mono text-xs {nameClass}" title={data.functionName}>
      {data.kind === "system" && data.functionName.startsWith("DBOS.")
        ? data.functionName.slice("DBOS.".length)
        : data.functionName}
    </span>
  {/if}
  {#if displayDurationMs !== null}
    <span class="text-muted-foreground ml-auto flex-none font-mono text-[10px]">
      {formatDuration(displayDurationMs)}
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
