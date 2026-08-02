<script lang="ts">
  import { onDestroy } from "svelte";
  import { fade } from "svelte/transition";
  import { prefersReducedMotion } from "svelte/motion";
  import { page } from "$app/state";
  import { replaceState } from "$app/navigation";
  import PanelRightOpen from "@lucide/svelte/icons/panel-right-open";
  import ResultPane, {
    type ResultData,
    type WorkflowEventEntry,
  } from "$lib/components/ResultPane.svelte";
  import WorkflowFlow, {
    type FamilyWorkflow,
    type FlowSelection,
    type Step,
  } from "$lib/components/WorkflowFlow.svelte";
  import WorkflowTimeline from "$lib/components/WorkflowTimeline.svelte";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";
  import { routeUrl } from "$lib/route-url";

  type WorkflowDetail = {
    workflow_id: string;
    parent_workflow_id: string | null;
    name: string | null;
    status: string | null;
    started_at: string;
    updated_at: string;
    completed_at: string | null;
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
  // Kept separate from `error` so a failed result fetch degrades to a message
  // inside the result pane instead of replacing the whole detail page.
  let resultError = $state<string | null>(null);
  // Token guards against stale fetches landing after a faster, newer click.
  let resultFetchToken = 0;

  const workflowId = $derived(page.params.id ?? "");


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

  // Graph vs timeline. The URL query wins (so links carry the view), then
  // the last locally chosen view, then the graph default. Changes rewrite
  // the query via replaceState — no history entry per toggle.
  type DetailView = "graph" | "timeline";
  const VIEW_KEY = "argus.workflowDetail.view";
  function loadView(): DetailView {
    const q = routeUrl(page.url).searchParams.get("view");
    if (q === "graph" || q === "timeline") return q;
    try {
      if (typeof localStorage !== "undefined" && localStorage.getItem(VIEW_KEY) === "timeline")
        return "timeline";
    } catch {
      // localStorage may be unavailable — fall through to the default.
    }
    return "graph";
  }
  let view = $state<DetailView>(loadView());
  // Crossfade between the two views. Read at transition start, so flipping the
  // OS reduced-motion setting takes effect without a reload; 0ms makes the
  // transition a no-op rather than needing a separate code path.
  const fadeMs = () => (prefersReducedMotion.current ? 0 : 130);
  // Timeline wait-compression, bound into WorkflowTimeline; the checkbox
  // itself lives in the switcher bar. wouldCompress is reported back by the
  // timeline so the checkbox only shows when compression would change
  // anything. On by default and persisted like the other pane settings.
  const COMPRESS_KEY = "argus.workflowDetail.timelineCompress";
  function loadCompress(): boolean {
    if (typeof localStorage === "undefined") return true;
    try {
      return localStorage.getItem(COMPRESS_KEY) !== "0";
    } catch {
      return true;
    }
  }
  let timelineCompress = $state(loadCompress());
  let timelineWouldCompress = $state(false);
  $effect(() => {
    if (typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(COMPRESS_KEY, timelineCompress ? "1" : "0");
    } catch {
      // Drop the write rather than crashing the effect.
    }
  });
  function setView(v: DetailView) {
    view = v;
    try {
      if (typeof localStorage !== "undefined") localStorage.setItem(VIEW_KEY, v);
    } catch {
      // Drop the write rather than crashing the handler.
    }
    // Under hash routing the route and its query live in the URL fragment —
    // rewrite the query inside the fragment, keeping the browser URL's
    // pathname (the mount point, e.g. a reverse-proxy prefix) untouched.
    const route = routeUrl(page.url);
    if (v === "graph") route.searchParams.delete("view");
    else route.searchParams.set("view", v);
    const url = new URL(page.url.href);
    url.hash = `#${route.pathname}${route.search}`;
    replaceState(url, {});
  }
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
  const MIN_RIGHT = 280;
  const MAX_RIGHT = 900;
  const RESIZE_STEP = 24;
  // Pane width survives reloads like `collapsed` above; clamped on load so a
  // stale or hand-edited value can't produce an unusable pane. Declared here
  // (not with the other pane state) because the loader needs the bounds.
  const WIDTH_KEY = "argus.workflowDetail.paneWidth";
  function loadWidth(): number {
    const fallback = 384; // matches the previous w-96
    if (typeof localStorage === "undefined") return fallback;
    try {
      const raw = localStorage.getItem(WIDTH_KEY);
      const n = raw === null ? NaN : Number(raw);
      if (!Number.isFinite(n)) return fallback;
      return Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, n));
    } catch {
      return fallback;
    }
  }
  let rightWidth = $state(loadWidth());
  $effect(() => {
    if (typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(WIDTH_KEY, String(rightWidth));
    } catch {
      // Drop the write rather than crashing the effect.
    }
  });

  function onHandlePointerDown(e: PointerEvent) {
    dragging = true;
    dragStartX = e.clientX;
    dragStartWidth = rightWidth;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onHandlePointerMove(e: PointerEvent) {
    if (!dragging) return;
    const delta = e.clientX - dragStartX;
    rightWidth = Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, dragStartWidth - delta));
  }

  function onHandlePointerUp(e: PointerEvent) {
    dragging = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }

  function onHandleKeyDown(e: KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();

    const step = e.shiftKey ? RESIZE_STEP * 2 : RESIZE_STEP;
    if (e.key === "ArrowLeft") {
      rightWidth = Math.min(MAX_RIGHT, rightWidth + step);
    } else {
      rightWidth = Math.max(MIN_RIGHT, rightWidth - step);
    }
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
    resultError = null;
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
      resultError = null;
      return;
    }
    let key: string;
    let url: string;
    let hasAny: boolean;
    if (sel.kind === "workflow") {
      key = `wf:${sel.workflow.workflow_id}`;
      // Relative (no leading slash) so it resolves against wherever the
      // console is mounted — root or behind a reverse-proxy prefix.
      url = `api/workflows/${encodeURIComponent(sel.workflow.workflow_id)}/result`;
      hasAny = sel.workflow.has_output || sel.workflow.has_error;
    } else {
      key = `step:${sel.step.workflow_id}:${sel.step.function_id}`;
      url =
        `api/workflows/${encodeURIComponent(sel.step.workflow_id)}` +
        `/steps/${sel.step.function_id}/result`;
      hasAny = sel.step.has_output || sel.step.has_error;
    }

    const cached = resultCache.get(key);
    if (cached) {
      result = cached;
      resultLoading = false;
      resultError = null;
      return;
    }

    // No payload to load — short-circuit with the empty sentinel and cache it
    // so toggling selection doesn't kick off a useless round-trip.
    if (!hasAny) {
      resultCache.set(key, EMPTY_RESULT);
      result = EMPTY_RESULT;
      resultLoading = false;
      resultError = null;
      return;
    }

    const myToken = ++resultFetchToken;
    result = null;
    resultLoading = true;
    resultError = null;
    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as ResultData;
        if (myToken !== resultFetchToken) return;
        resultCache.set(key, body);
        result = body;
        resultLoading = false;
        resultError = null;
      })
      .catch((e) => {
        if (myToken !== resultFetchToken) return;
        resultLoading = false;
        resultError = e instanceof Error ? e.message : String(e);
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
      { label: "Workflows", href: "#/workflows/", icon: "workflow", tooltip: "Workflows" },
      ...chain.map((w) => ({
        label: w.name ?? w.workflow_id,
        href: `#/workflows/${encodeURIComponent(w.workflow_id)}/`,
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
  <div
    class="relative flex min-h-0 flex-1 overflow-hidden"
    class:select-none={dragging}
  >
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <!-- In-flow switcher bar: sits above the graph/timeline instead of
           floating over them. pl-4 lines the toggle up with the sidebar
           trigger's glyph in the header (header pl-3, and the trigger's
           ghost-button box starts 8px further left than its glyph).
           [&_button]:text-xs mirrors the workflow list's filter row so
           toggle labels match that toolbar's type size. -->
      <div
        class="flex flex-none items-center justify-between pt-1 pb-1 pl-4 [&_button]:text-xs"
      >
        <ToggleGroup.Root
          class="bg-card shadow-surface rounded-lg"
          type="single"
          variant="outline"
          value={view}
          onValueChange={(v) => {
            if (v === "graph" || v === "timeline") setView(v);
          }}
        >
          <ToggleGroup.Item value="graph" class="h-7 px-2.5">Graph</ToggleGroup.Item>
          <ToggleGroup.Item value="timeline" class="h-7 px-2.5">Timeline</ToggleGroup.Item>
        </ToggleGroup.Root>
        <div class="flex items-center gap-2">
          {#if view === "timeline" && timelineWouldCompress}
            <!-- A boolean with a clear default, so it reads as a checkbox
                 rather than a two-way switch; same treatment as the workflow
                 list's "Hide scheduled". The tooltip carries what the
                 unchecked state means. -->
            <label
              class="bg-card shadow-surface hover:bg-muted hover:text-foreground text-foreground flex h-8 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium select-none dark:hover:bg-input/30"
              title="Collapse long waits between steps; uncheck for a true linear time scale"
            >
              <Checkbox
                checked={timelineCompress}
                onCheckedChange={(v) => (timelineCompress = !!v)}
              />
              Compress waits
            </label>
          {/if}
          {#if collapsed}
            <!-- Collapsed: the pane gives its space back to the graph and
                 leaves only this expand button behind. -->
            <button
              type="button"
              onclick={() => (collapsed = false)}
              title="Expand details pane"
              aria-label="Expand details pane"
              class="bg-card shadow-surface text-muted-foreground hover:text-foreground hover:bg-muted flex h-8 w-8 items-center justify-center rounded-lg"
            >
              <PanelRightOpen class="size-4" />
            </button>
          {/if}
        </div>
      </div>
      <!-- Both views are absolutely positioned so they can overlap for the
           length of the crossfade, and because the app shell is a min-height
           layout: a tall trace left in flow would push the whole document
           instead of scrolling inside the timeline. Out-of-flow, each settles
           at the viewport-bounded stretch size (the same reason the xyflow
           canvas works) and the timeline's own scroller engages. -->
      <div class="relative min-h-0 flex-1">
        {#if view === "graph"}
          <div class="absolute inset-0" transition:fade={{ duration: fadeMs() }}>
            <WorkflowFlow
              family={detail.family}
              steps={detail.steps}
              currentId={detail.workflow_id}
              {selection}
              onSelect={(s) => (selection = s)}
            />
          </div>
        {:else}
          <div class="absolute inset-0" transition:fade={{ duration: fadeMs() }}>
            <WorkflowTimeline
              family={detail.family}
              steps={detail.steps}
              currentId={detail.workflow_id}
              {selection}
              onSelect={(s) => (selection = s)}
              bind:compress={timelineCompress}
              bind:wouldCompress={timelineWouldCompress}
            />
          </div>
        {/if}
      </div>
    </div>
    {#if !collapsed}
      <div
        class="relative hidden w-px flex-none lg:block"
        class:!bg-primary={dragging}
      >
        <button
          type="button"
          aria-label={`Resize result pane. Current width ${rightWidth} pixels. Use Left and Right arrow keys.`}
          aria-keyshortcuts="ArrowLeft ArrowRight"
          title="Resize details pane with Left and Right arrow keys"
          onpointerdown={onHandlePointerDown}
          onpointermove={onHandlePointerMove}
          onpointerup={onHandlePointerUp}
          onkeydown={onHandleKeyDown}
          class="bg-card shadow-surface text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:ring-ring absolute top-1/2 left-1/2 z-10 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 cursor-col-resize items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none"
          class:!bg-primary={dragging}
          class:!text-primary-foreground={dragging}
        >
          <span class="flex h-3 items-center gap-0.5">
            <span class="bg-current h-full w-px"></span>
            <span class="bg-current h-full w-px"></span>
          </span>
        </button>
      </div>
    {/if}
    <!-- Collapse animates the wrapper's width to 0 (not `hidden`, which can't
         transition). The inner holder keeps the pane's real width and anchors
         right, so content neither reflows nor drifts while the left edge
         sweeps shut. `visibility` rides the transition so it flips only at
         the end (hiding the zero-width shadow sliver); `inert` keeps focus
         out of the closed pane. -->
    <div
      class="shadow-surface-lg absolute top-1 right-3 bottom-3 flex w-[var(--result-pane-width)] max-w-[calc(100%-3rem)] flex-none justify-end overflow-hidden rounded-xl lg:static lg:mt-1 lg:mr-3 lg:mb-3 lg:ml-2"
      class:invisible={collapsed}
      inert={collapsed}
      class:transition-[width,visibility]={!dragging}
      class:duration-200={!dragging}
      class:ease-in-out={!dragging}
      style="--result-pane-width: {collapsed ? 0 : rightWidth}px"
    >
      <div class="h-full max-w-[calc(100vw-3rem)]" style="width: {rightWidth}px">
        <ResultPane
          {selection}
          {result}
          loading={resultLoading}
          loadError={resultError}
          events={detail.events}
          onToggleCollapse={() => (collapsed = !collapsed)}
        />
      </div>
    </div>
  </div>
{/if}
