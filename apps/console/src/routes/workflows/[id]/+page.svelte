<script lang="ts">
  import { page } from "$app/state";
  import ResultPane from "$lib/components/ResultPane.svelte";
  import WorkflowFlow, {
    type FamilyWorkflow,
    type FlowSelection,
    type Step,
  } from "$lib/components/WorkflowFlow.svelte";

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
  <div class="flex h-[calc(100vh-4rem)] gap-4 p-6">
    <div class="min-w-0 flex-1">
      <WorkflowFlow
        family={detail.family}
        steps={detail.steps}
        currentId={detail.workflow_id}
        {selection}
        onSelect={(s) => (selection = s)}
      />
    </div>
    <div class="w-96 flex-none">
      <ResultPane {selection} />
    </div>
  </div>
{/if}
