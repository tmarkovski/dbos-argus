<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import { statusBadgeClass, type Workflow } from "$lib/workflow-tree";

  type NodeData = { workflow: Workflow; isCurrent: boolean };

  let { data, selected }: NodeProps & { data: NodeData } = $props();
</script>

<div
  class="bg-card/60 flex h-full w-full cursor-pointer flex-col rounded-lg border backdrop-blur-sm
    {selected
      ? 'ring-primary border-primary ring-2'
      : data.isCurrent
        ? 'ring-primary/40 border-primary/60 ring-2'
        : 'border-border'}"
>
  <Handle type="target" position={Position.Top} isConnectable={false} />
  <div class="border-border bg-card/80 flex items-center gap-2 rounded-t-lg border-b px-3 py-2">
    <span class="truncate font-mono text-xs font-medium">
      {data.workflow.name ?? "—"}
    </span>
    <span
      class="ml-auto inline-flex flex-none items-center rounded-full px-1.5 py-0 text-[10px] font-medium ring-1 ring-inset {statusBadgeClass(
        data.workflow.status,
      )}"
    >
      {data.workflow.status ?? "—"}
    </span>
  </div>
  <div
    class="text-muted-foreground truncate px-3 py-0.5 font-mono text-[10px]"
    title={data.workflow.workflow_id}
  >
    {data.workflow.workflow_id}
  </div>
  <Handle type="source" position={Position.Bottom} isConnectable={false} />
</div>
