<script lang="ts">
  import type { WorkflowGraphProps } from "./types.js";

  let { nodes, edges }: WorkflowGraphProps = $props();
</script>

<div class="argus-workflow-graph" data-testid="workflow-graph">
  <p>WorkflowGraph stub — {nodes.length} nodes, {edges.length} edges.</p>
</div>
