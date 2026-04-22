<script lang="ts">
  import {
    SvelteFlow,
    Background,
    Controls,
    type Node,
    type Edge,
  } from "@xyflow/svelte";

  let nodes = $state.raw<Node[]>([
    {
      id: "1",
      type: "default",
      data: { label: "start" },
      position: { x: 0, y: 0 },
    },
    {
      id: "2",
      type: "default",
      data: { label: "done" },
      position: { x: 220, y: 120 },
    },
  ]);

  let edges = $state.raw<Edge[]>([
    { id: "e1-2", source: "1", target: "2", animated: true },
  ]);
</script>

<div class="flex flex-col gap-4 p-6">
  <p class="text-sm text-neutral-500">
    Self-hosted console for DBOS Transact — pre-alpha.
  </p>

  <section class="flex-1 rounded border border-neutral-300 p-3">
    <h2 class="text-sm font-medium uppercase tracking-wide text-neutral-500">
      Workflow graph (demo)
    </h2>
    <div style="width:100%;height:400px;">
      <SvelteFlow bind:nodes bind:edges fitView>
        <Background />
        <Controls />
      </SvelteFlow>
    </div>
  </section>
</div>
