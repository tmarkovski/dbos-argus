<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import ChevronsDown from "@lucide/svelte/icons/chevrons-down";

  type NodeData = { workflowId: string; hiddenCount: number };

  let { data }: NodeProps & { data: NodeData } = $props();
</script>

<div
  class="text-muted-foreground hover:text-foreground flex h-full w-full cursor-pointer items-center justify-center gap-1.5 px-2.5 py-1 font-mono text-[10px] transition-colors"
>
  <Handle type="target" position={Position.Top} isConnectable={false} />
  <ChevronsDown class="h-3 w-3" />
  <span>··· {data.hiddenCount} more {data.hiddenCount === 1 ? "step" : "steps"} ···</span>
  <ChevronsDown class="h-3 w-3" />
  <Handle type="source" position={Position.Bottom} isConnectable={false} />
</div>
