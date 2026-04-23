<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";

  type StepKind = "step" | "child" | "system";
  type StepStatus = "error" | "running" | "success" | null;

  type NodeData = {
    functionId: number;
    functionName: string;
    kind: StepKind;
    status: StepStatus;
    durationMs: number | null;
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
    if (ms < 1000) return `${ms}ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)}s`;
    return `${(s / 60).toFixed(1)}m`;
  }
</script>

<div
  class="bg-background flex h-full w-full cursor-pointer items-center gap-2 rounded-md border border-border/70 px-2.5 py-1 shadow-xs transition-shadow hover:shadow-md
    {selected ? 'ring-primary ring-2 border-primary' : ''}"
>
  <Handle type="target" position={Position.Left} isConnectable={false} />
  <span class="h-2 w-2 flex-none rounded-full {dotClass}" aria-hidden="true"></span>
  <span class="text-muted-foreground flex-none font-mono text-[10px]">#{data.functionId}</span>
  <span class="truncate font-mono text-xs {nameClass}" title={data.functionName}>
    {data.functionName}
  </span>
  {#if data.durationMs !== null}
    <span class="text-muted-foreground ml-auto flex-none font-mono text-[10px]">
      {formatDuration(data.durationMs)}
    </span>
  {/if}
  <Handle type="source" position={Position.Right} isConnectable={false} />
</div>
