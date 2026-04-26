<script lang="ts">
  import { onDestroy } from "svelte";
  import { page } from "$app/state";
  import ResultPane from "$lib/components/ResultPane.svelte";
  import WorkflowFlow, {
    type FamilyWorkflow,
    type FlowSelection,
    type Step,
  } from "$lib/components/WorkflowFlow.svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";

  type WorkflowDetail = {
    workflow_id: string;
    parent_workflow_id: string | null;
    name: string | null;
    status: string | null;
    started_at: string;
    updated_at: string;
    family: FamilyWorkflow[];
    steps: Step[];
  };

  let detail = $state<WorkflowDetail | null>(null);
  let error = $state<string | null>(null);
  let selection = $state<FlowSelection>(null);

  const workflowId = $derived(page.params.id ?? "");

  let rightWidth = $state(384); // matches the previous w-96
  let dragging = $state(false);
  let dragStartX = 0;
  let dragStartWidth = 0;
  const MIN_RIGHT = 280;
  const MAX_RIGHT = 900;

  function onHandlePointerDown(e: PointerEvent) {
    dragging = true;
    dragStartX = e.clientX;
    dragStartWidth = rightWidth;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onHandlePointerMove(e: PointerEvent) {
    if (!dragging) return;
    const delta = e.clientX - dragStartX;
    const next = dragStartWidth - delta;
    rightWidth = Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, next));
  }

  function onHandlePointerUp(e: PointerEvent) {
    dragging = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }

  $effect(() => {
    const id = workflowId;
    detail = null;
    error = null;
    selection = null;
    if (!id) return;
    fetch(`/api/workflows/${encodeURIComponent(id)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as WorkflowDetail;
        detail = body;
        // Default to showing the current workflow's result.
        const self = body.family.find((w) => w.workflow_id === body.workflow_id);
        selection = self ? { kind: "workflow", workflow: self } : null;
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : String(e);
      });
  });

  // Walk parent_workflow_id pointers up the family graph to build a
  // root → ... → current chain, then publish to the global breadcrumb.
  $effect(() => {
    if (!detail) {
      breadcrumb.items = [];
      return;
    }
    const byId = new Map(detail.family.map((w) => [w.workflow_id, w]));
    const chain: FamilyWorkflow[] = [];
    let cur: FamilyWorkflow | undefined = byId.get(detail.workflow_id);
    while (cur) {
      chain.unshift(cur);
      cur = cur.parent_workflow_id ? byId.get(cur.parent_workflow_id) : undefined;
    }
    breadcrumb.items = [
      { label: "Home", href: "/", icon: "home", tooltip: "Home" },
      ...chain.map((w) => ({
        label: w.name ?? w.workflow_id,
        href: `/workflows/${w.workflow_id}`,
        status: w.status,
        tooltip: w.workflow_id,
      })),
    ];
  });

  onDestroy(() => {
    breadcrumb.items = [];
  });
</script>

{#if error}
  <div class="p-6">
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  </div>
{:else if detail === null}
  <p class="text-muted-foreground p-6 text-sm">Loading…</p>
{:else}
  <div class="flex h-[calc(100vh-4rem)]" class:select-none={dragging}>
    <div class="min-w-0 flex-1">
      <WorkflowFlow
        family={detail.family}
        steps={detail.steps}
        currentId={detail.workflow_id}
        {selection}
        onSelect={(s) => (selection = s)}
      />
    </div>
    <div class="bg-border relative w-px flex-none" class:!bg-primary={dragging}>
      <button
        type="button"
        aria-label="Resize result pane"
        onpointerdown={onHandlePointerDown}
        onpointermove={onHandlePointerMove}
        onpointerup={onHandlePointerUp}
        class="bg-card border-border text-muted-foreground hover:text-foreground hover:bg-muted absolute top-1/2 left-1/2 z-10 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 cursor-col-resize items-center justify-center rounded-full border shadow-sm"
        class:!bg-primary={dragging}
        class:!border-primary={dragging}
        class:!text-primary-foreground={dragging}
      >
        <span class="flex h-3 items-center gap-0.5">
          <span class="bg-current h-full w-px"></span>
          <span class="bg-current h-full w-px"></span>
        </span>
      </button>
    </div>
    <div class="flex-none" style="width: {rightWidth}px">
      <ResultPane {selection} />
    </div>
  </div>
{/if}
