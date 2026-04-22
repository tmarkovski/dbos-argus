<script lang="ts">
  import { onMount } from "svelte";
  import {
    SvelteFlow,
    Background,
    Controls,
    type Node,
    type Edge,
  } from "@xyflow/svelte";
  import { env } from "$env/dynamic/public";

  const apiUrl: string = env.PUBLIC_ARGUS_API_URL ?? "http://localhost:8090";

  let status = $state<string>("loading…");
  let error = $state<string | null>(null);

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

  onMount(async () => {
    try {
      const res = await fetch(`${apiUrl}/healthz`);
      const data = await res.json();
      status = data.status ?? "unknown";
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      status = "unreachable";
    }
  });
</script>

<main class="p-6 flex flex-col gap-4">
  <header>
    <h1 class="text-3xl font-semibold">Argus</h1>
    <p class="text-sm text-neutral-500">
      Self-hosted console for DBOS Transact — pre-alpha.
    </p>
  </header>

  <section class="rounded border border-neutral-300 p-3">
    <h2 class="text-sm font-medium uppercase tracking-wide text-neutral-500">
      Backend
    </h2>
    <p>
      <span class="font-mono">{apiUrl}/healthz</span> —
      <strong>{status}</strong>
      {#if error}
        <span class="text-red-600">({error})</span>
      {/if}
    </p>
  </section>

  <section class="rounded border border-neutral-300 p-3 flex-1">
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
</main>
