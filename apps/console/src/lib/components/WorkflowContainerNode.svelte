<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import ChevronsUp from "@lucide/svelte/icons/chevrons-up";
  import { statusBadgeClass, type Workflow } from "$lib/workflow-tree";
  import { Badge } from "$lib/components/ui/badge/index.js";

  type NodeData = {
    workflow: Workflow;
    isCurrent: boolean;
    isCollapsible: boolean;
    isExpanded: boolean;
    onToggle?: () => void;
  };

  let { data, selected }: NodeProps & { data: NodeData } = $props();

  function handleToggle(e: MouseEvent) {
    e.stopPropagation();
    data.onToggle?.();
  }
</script>

<div
  class="bg-card relative flex h-full w-full cursor-pointer flex-col rounded-2xl border
    {selected
      ? 'border-primary shadow-md'
      : data.isCurrent
        ? 'border-primary/50 shadow-sm'
        : 'border-foreground/15 shadow-sm'}"
>
  <Handle
    id="spawn"
    type="target"
    position={Position.Left}
    style="top: 35%"
    isConnectable={false}
  />
  <Handle
    id="return"
    type="source"
    position={Position.Left}
    style="top: 65%"
    isConnectable={false}
  />
  <div class="flex items-center gap-2 px-3 py-2">
    <span class="truncate font-mono text-xs font-medium">
      {data.workflow.name ?? "—"}
    </span>
    <Badge class="ml-auto {statusBadgeClass(data.workflow.status)}">
      {data.workflow.status ?? "—"}
    </Badge>
  </div>
  <div
    class="text-muted-foreground truncate px-3 py-0.5 font-mono text-[10px]"
    title={data.workflow.workflow_id}
  >
    {data.workflow.workflow_id}
  </div>
  {#if data.isCollapsible && data.isExpanded}
    <button
      type="button"
      onclick={handleToggle}
      onmousedown={(e) => e.stopPropagation()}
      class="border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted absolute -left-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border shadow-sm"
      aria-label="Collapse steps"
      title="Collapse"
    >
      <ChevronsUp class="h-3.5 w-3.5" />
    </button>
    <button
      type="button"
      onclick={handleToggle}
      onmousedown={(e) => e.stopPropagation()}
      class="border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted absolute -right-3 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border shadow-sm"
      aria-label="Collapse steps"
      title="Collapse"
    >
      <ChevronsUp class="h-3.5 w-3.5" />
    </button>
  {/if}
</div>
