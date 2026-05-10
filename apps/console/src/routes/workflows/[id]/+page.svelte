<script lang="ts">
  import { onDestroy } from "svelte";
  import { page } from "$app/state";
  import ResultPane, {
    type ResultData,
    type WorkflowEventEntry,
  } from "$lib/components/ResultPane.svelte";
  import WorkflowFlow, {
    type FamilyWorkflow,
    type FlowSelection,
    type Step,
  } from "$lib/components/WorkflowFlow.svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type WorkflowDetail = {
    workflow_id: string;
    parent_workflow_id: string | null;
    name: string | null;
    status: string | null;
    started_at: string;
    updated_at: string;
    family: FamilyWorkflow[];
    steps: Step[];
    events: WorkflowEventEntry[];
  };

  let detail = $state<WorkflowDetail | null>(null);
  let error = $state<string | null>(null);
  let selection = $state<FlowSelection>(null);

  // Result payloads are loaded lazily on selection and cached for the lifetime
  // of this page so navigating between previously-viewed workflows / steps
  // doesn't re-hit the server. Map keys: `wf:<id>` and `step:<wf>:<fnId>`.
  // The empty-result sentinel ({output:null,error:null,...}) is also cached
  // so we don't refetch rows known to have no payload. Plain Map (not $state)
  // because we read it inside an effect and don't want it triggering itself.
  const resultCache = new Map<string, ResultData>();
  const EMPTY_RESULT: ResultData = {
    output: null,
    error: null,
    serialization: null,
    output_decoded: null,
    error_decoded: null,
  };
  let result = $state<ResultData | null>(null);
  let resultLoading = $state(false);
  // Token guards against stale fetches landing after a faster, newer click.
  let resultFetchToken = 0;

  const workflowId = $derived(page.params.id ?? "");

  let rightWidth = $state(384); // matches the previous w-96

  // Side pane collapsed state survives reloads — same convention as the
  // sidebar / workflow filters (`argus.*` key, hydrated at script init
  // since the console runs with `ssr = false`).
  const COLLAPSED_KEY = "argus.workflowDetail.detailsCollapsed";
  function loadCollapsed(): boolean {
    if (typeof localStorage === "undefined") return false;
    try {
      return localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  }
  let collapsed = $state(loadCollapsed());
  $effect(() => {
    if (typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) — drop
      // the write rather than crashing the effect.
    }
  });

  let dragging = $state(false);
  let dragStartX = 0;
  let dragStartWidth = 0;
  // Width to restore if a drag-from-collapsed releases below MIN_RIGHT.
  let savedRightWidth = 0;
  let dragFromCollapsed = false;
  const MIN_RIGHT = 280;
  const MAX_RIGHT = 900;
  // Width left visible when collapsed: just enough to show the eyebrow's
  // 32px (icon-sm) toggle button + the eyebrow's px-4 horizontal padding.
  const PEEK_WIDTH = 64;

  const effectiveRightWidth = $derived(collapsed ? PEEK_WIDTH : rightWidth);

  function onHandlePointerDown(e: PointerEvent) {
    dragging = true;
    dragStartX = e.clientX;
    dragFromCollapsed = collapsed;
    if (collapsed) {
      // Drag from collapsed: anchor the drag at the peek width so the pane
      // grows out of the peek under the cursor instead of jumping straight
      // to the saved expanded width.
      savedRightWidth = rightWidth;
      dragStartWidth = PEEK_WIDTH;
      rightWidth = PEEK_WIDTH;
      collapsed = false;
    } else {
      dragStartWidth = rightWidth;
    }
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onHandlePointerMove(e: PointerEvent) {
    if (!dragging) return;
    const delta = e.clientX - dragStartX;
    const next = dragStartWidth - delta;
    // Drag-from-collapsed allows widths down to PEEK_WIDTH so the user can
    // back out of an expand. Drag-from-expanded keeps MIN_RIGHT so the pane
    // stays usable.
    const min = dragFromCollapsed ? PEEK_WIDTH : MIN_RIGHT;
    rightWidth = Math.max(min, Math.min(MAX_RIGHT, next));
  }

  function onHandlePointerUp(e: PointerEvent) {
    dragging = false;
    if (dragFromCollapsed && rightWidth < MIN_RIGHT) {
      // Released without expanding past MIN_RIGHT — snap back to collapsed
      // and restore the previously-expanded width for next expand.
      collapsed = true;
      rightWidth = savedRightWidth;
    }
    dragFromCollapsed = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }

  let workflowHandle: SubscriptionHandle | null = null;
  // First snapshot for a given workflow seeds `selection`; subsequent updates
  // must NOT clobber the user's choice — they may have clicked a step.
  let selectionSeeded = false;

  $effect(() => {
    const id = workflowId;
    detail = null;
    error = null;
    selection = null;
    selectionSeeded = false;
    // Different workflow → wipe cache; a stale entry from a previous
    // workflow's family would never be hit anyway, but cleanup keeps memory
    // bounded across navigations.
    resultCache.clear();
    result = null;
    resultLoading = false;
    if (!id) return;

    const apply = (data: unknown) => {
      // Server sends `null` when the workflow doesn't exist (or the dbos
      // schema isn't provisioned yet) — surface that as an error so the
      // page renders the same "not found" state the old REST 404 produced.
      if (data === null) {
        error = "workflow not found";
        return;
      }
      const body = data as WorkflowDetail;
      detail = body;
      error = null;
      if (!selectionSeeded) {
        const self = body.family.find((w) => w.workflow_id === body.workflow_id);
        selection = self ? { kind: "workflow", workflow: self } : null;
        selectionSeeded = true;
        return;
      }
      // Re-point the selection at the fresh objects so the result pane sees
      // updated has_output / has_error / status flags. Match by id; if the
      // selected node disappears (rare — would mean a step or workflow
      // vanished), drop selection rather than show stale data.
      const cur = selection;
      if (cur === null) return;
      if (cur.kind === "workflow") {
        const fresh = body.family.find((w) => w.workflow_id === cur.workflow.workflow_id);
        selection = fresh ? { kind: "workflow", workflow: fresh } : null;
      } else {
        const fresh = body.steps.find(
          (s) =>
            s.workflow_id === cur.step.workflow_id && s.function_id === cur.step.function_id,
        );
        selection = fresh ? { kind: "step", step: fresh } : null;
      }
    };

    const handle = realtimeClient.subscribe(
      "workflow",
      { id },
      {
        onSnapshot: apply,
        onUpdate: apply,
        onError: (_code, message) => {
          error = message;
        },
      },
    );
    workflowHandle = handle;

    return () => {
      handle.dispose();
      if (workflowHandle === handle) workflowHandle = null;
    };
  });

  $effect(() => {
    const sel = selection;
    if (!sel) {
      result = null;
      resultLoading = false;
      return;
    }
    let key: string;
    let url: string;
    let hasAny: boolean;
    if (sel.kind === "workflow") {
      key = `wf:${sel.workflow.workflow_id}`;
      url = `/api/workflows/${encodeURIComponent(sel.workflow.workflow_id)}/result`;
      hasAny = sel.workflow.has_output || sel.workflow.has_error;
    } else {
      key = `step:${sel.step.workflow_id}:${sel.step.function_id}`;
      url =
        `/api/workflows/${encodeURIComponent(sel.step.workflow_id)}` +
        `/steps/${sel.step.function_id}/result`;
      hasAny = sel.step.has_output || sel.step.has_error;
    }

    const cached = resultCache.get(key);
    if (cached) {
      result = cached;
      resultLoading = false;
      return;
    }

    // No payload to load — short-circuit with the empty sentinel and cache it
    // so toggling selection doesn't kick off a useless round-trip.
    if (!hasAny) {
      resultCache.set(key, EMPTY_RESULT);
      result = EMPTY_RESULT;
      resultLoading = false;
      return;
    }

    const myToken = ++resultFetchToken;
    result = null;
    resultLoading = true;
    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as ResultData;
        if (myToken !== resultFetchToken) return;
        resultCache.set(key, body);
        result = body;
        resultLoading = false;
      })
      .catch((e) => {
        if (myToken !== resultFetchToken) return;
        resultLoading = false;
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
      { label: "Workflows", href: "/workflows/", icon: "workflow", tooltip: "Workflows" },
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
    <div
      class="flex-none overflow-hidden"
      class:transition-[width]={!dragging}
      class:duration-200={!dragging}
      class:ease-out={!dragging}
      style="width: {effectiveRightWidth}px"
    >
      <ResultPane
        {selection}
        {result}
        loading={resultLoading}
        events={detail.events}
        {collapsed}
        onToggleCollapse={() => (collapsed = !collapsed)}
      />
    </div>
  </div>
{/if}
