<script lang="ts" module>
  // Last enqueued snapshot, kept at module scope for the SPA session so
  // returning to this page (back/forward, or just navigating around) paints
  // the strip already in place instead of replaying the reveal every time.
  // Keyed by queue scope: the strip narrows to `?queue_name=`, and the two
  // scopes must not seed each other. A full page reload starts cold, matching
  // the graph's view memory in WorkflowFlow.svelte.
  //
  // Short-lived on purpose. These rows are live state, and the cached copy is
  // only meant to cover the ~100ms until the socket's first snapshot lands —
  // past that it would be showing a count that stopped being true a while ago.
  const ENQUEUED_CACHE_TTL_MS = 30_000;
  type EnqueuedCache = { rows: import("$lib/workflow-tree").Workflow[]; at: number };
  const enqueuedCache = new Map<string, EnqueuedCache>();

  function readEnqueuedCache(queue: string): EnqueuedCache["rows"] | null {
    const hit = enqueuedCache.get(queue);
    if (!hit) return null;
    if (Date.now() - hit.at > ENQUEUED_CACHE_TTL_MS) {
      enqueuedCache.delete(queue);
      return null;
    }
    return hit.rows;
  }
</script>

<script lang="ts">
  import { onDestroy, onMount, untrack } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { getLocalTimeZone, parseDate, type DateValue } from "@internationalized/date";
  import FilterIcon from "@lucide/svelte/icons/list-filter";
  import FilterXIcon from "@lucide/svelte/icons/filter-x";
  import SearchIcon from "@lucide/svelte/icons/search";
  import ColumnsIcon from "@lucide/svelte/icons/columns-3";
  import CheckIcon from "@lucide/svelte/icons/check";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import CalendarClockIcon from "@lucide/svelte/icons/calendar-clock";
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { prefersReducedMotion } from "svelte/motion";
  import DateRangePicker from "$lib/components/DateRangePicker.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Separator } from "$lib/components/ui/separator";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Popover from "$lib/components/ui/popover";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import {
    computeLineage,
    formatStatus,
    statusBadgeClass,
    type TreeRow,
    type Workflow,
  } from "$lib/workflow-tree";
  import { STATUS_LABELS, WORKFLOW_STATUSES } from "$lib/workflow-status";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { statsState } from "$lib/stats.svelte";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";
  import { routeUrl } from "$lib/route-url";

  const queueName = $derived(routeUrl(page.url).searchParams.get("queue_name") ?? "");

  $effect(() => {
    breadcrumb.items = queueName
      ? [
          { label: "Workflows", href: "#/workflows/", icon: "workflow" },
          { label: `Queue: ${queueName}` },
        ]
      : [{ label: "Workflows", icon: "workflow" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  type ColumnKey =
    | "name"
    | "status"
    | "workflow_id"
    | "started"
    | "executor_id"
    | "queue_name";

  let workflows = $state<Workflow[] | null>(null);
  // ENQUEUED rows live in a pinned strip above the main list; the server
  // hides them from /api/workflows by default, and the strip subscribes
  // separately with `status: ["ENQUEUED"]`.
  // Seeded from the session cache when there is a fresh entry for this scope,
  // so a return visit renders the strip in its final position on the first
  // frame; the socket's snapshot corrects it a moment later.
  const cachedEnqueued = readEnqueuedCache(untrack(() => queueName));
  let enqueued = $state<Workflow[]>(cachedEnqueued ?? []);
  // The strip's snapshot lands ~30ms after the main list's, and the strip sits
  // above everything — arriving that close to the list's own first paint, it
  // reads as the page glitching rather than as something appearing. Holding it
  // a beat past the list separates the two, and the slide below then carries
  // the movement instead of dropping it in one frame. A cache hit skips the
  // staging entirely: there is nothing to announce, the strip was already
  // there last time we looked.
  const STRIP_REVEAL_DELAY_MS = 180;
  let stripVisible = $state((cachedEnqueued?.length ?? 0) > 0);
  $effect(() => {
    if (enqueued.length === 0) {
      stripVisible = false;
      return;
    }
    const t = setTimeout(() => (stripVisible = true), STRIP_REVEAL_DELAY_MS);
    return () => clearTimeout(t);
  });
  // Collapse state survives reloads/navigation; SSR has no window so the
  // initial value defaults to collapsed and gets corrected on hydrate if the
  // user has previously toggled it open.
  const ENQUEUED_COLLAPSED_KEY = "argus.workflows.enqueuedCollapsed";
  let enqueuedCollapsed = $state(true);
  let error = $state<string | null>(null);
  // Realtime subscription handles. The page holds two: the main filtered
  // list and the pinned ENQUEUED strip. Both push fresh snapshots whenever
  // anything in dbos.workflow_status / operation_outputs changes.
  let mainHandle: SubscriptionHandle | null = null;
  let enqueuedHandle: SubscriptionHandle | null = null;
  // Queue names for the Queue filter popover, kept live via the same realtime
  // channel the queues page subscribes to.
  let queueList = $state<string[]>([]);
  let queuesHandle: SubscriptionHandle | null = null;
  let queuePopoverOpen = $state(false);

  // Filter options derived from the canonical status list — adding a new DBOS
  // workflow status only requires editing `$lib/workflow-status.ts`. ENQUEUED
  // is intentionally omitted: those rows live in the pinned strip above the
  // main list, not as a filterable status here.
  const STATUS_OPTIONS = WORKFLOW_STATUSES.filter((s) => s !== "ENQUEUED").map((value) => ({
    value,
    label: STATUS_LABELS[value],
  }));
  const allStatuses = () => new Set(STATUS_OPTIONS.map((o) => o.value));

  // Filter persistence: search/date-range/statuses survive reloads. The
  // existing hideScheduled and enqueuedCollapsed keys follow the same scheme.
  // `ssr = false` in +layout.ts means localStorage is available at script
  // init, so we can hydrate state directly instead of patching it in onMount.
  const Q_KEY = "argus.workflows.q";
  const DATE_RANGE_KEY = "argus.workflows.dateRange";
  const STATUSES_KEY = "argus.workflows.statuses";

  function readStored(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) — fall back
      // to defaults.
      return null;
    }
  }
  function writeStored(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // see readStored note
    }
  }
  function removeStored(key: string) {
    try {
      localStorage.removeItem(key);
    } catch {
      // see readStored note
    }
  }

  function hydrateDateRange(): { start: DateValue | undefined; end: DateValue | undefined } {
    const raw = readStored(DATE_RANGE_KEY);
    if (!raw) return { start: undefined, end: undefined };
    try {
      const parsed = JSON.parse(raw) as { start?: string | null; end?: string | null };
      const start = parsed.start ? parseDate(parsed.start) : undefined;
      const end = parsed.end ? parseDate(parsed.end) : undefined;
      return { start, end };
    } catch {
      return { start: undefined, end: undefined };
    }
  }
  function hydrateStatuses(): Set<string> {
    const raw = readStored(STATUSES_KEY);
    if (raw === null) return allStatuses();
    try {
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return allStatuses();
      const valid = new Set<string>(STATUS_OPTIONS.map((o) => o.value));
      return new Set(arr.filter((v): v is string => typeof v === "string" && valid.has(v)));
    } catch {
      return allStatuses();
    }
  }

  // `qInput` is what the user is typing right now; `filters.q` is what the
  // backend actually filters on. We debounce input → applied so we don't
  // round-trip per keystroke, and require at least SEARCH_MIN_CHARS before
  // firing — single-character queries are too broad to be useful.
  const SEARCH_DEBOUNCE_MS = 500;
  const SEARCH_MIN_CHARS = 2;
  // Read the persisted query into a local first so we can seed both `qInput`
  // and `filters.q` without reading `$state` during construction (which Svelte
  // warns about — the initializer wouldn't update if the underlying state
  // changed later).
  const persistedQ = readStored(Q_KEY) ?? "";
  let qInput = $state(persistedQ);
  let filters = $state({
    // Seed `filters.q` directly from the hydrated input so the first refresh
    // already includes the persisted search instead of waiting one debounce
    // tick to apply it.
    q: persistedQ.trim().length >= SEARCH_MIN_CHARS ? persistedQ.trim() : "",
  });
  let qDebounce: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = qInput.trim();
    if (qDebounce) clearTimeout(qDebounce);
    if (next.length < SEARCH_MIN_CHARS) {
      // Below threshold (or empty): drop the filter immediately so visible
      // data doesn't lag behind the input.
      if (filters.q !== "") filters.q = "";
      return;
    }
    qDebounce = setTimeout(() => {
      filters.q = next;
    }, SEARCH_DEBOUNCE_MS);
  });
  let dateRange = $state<{ start: DateValue | undefined; end: DateValue | undefined }>(
    hydrateDateRange(),
  );

  let selectedStatuses = $state<Set<string>>(hydrateStatuses());

  // Persist filters on change. Empty/default values are removed rather than
  // written so a fresh install with no prior key looks the same as a user who
  // cleared their filters.
  $effect(() => {
    if (qInput === "") removeStored(Q_KEY);
    else writeStored(Q_KEY, qInput);
  });
  $effect(() => {
    const start = dateRange.start ? dateRange.start.toString() : null;
    const end = dateRange.end ? dateRange.end.toString() : null;
    if (start === null && end === null) removeStored(DATE_RANGE_KEY);
    else writeStored(DATE_RANGE_KEY, JSON.stringify({ start, end }));
  });
  $effect(() => {
    if (
      selectedStatuses.size === STATUS_OPTIONS.length &&
      STATUS_OPTIONS.every((o) => selectedStatuses.has(o.value))
    ) {
      removeStored(STATUSES_KEY);
    } else {
      writeStored(STATUSES_KEY, JSON.stringify(Array.from(selectedStatuses)));
    }
  });
  // Scheduled workflows (id prefix `sched-`) are shown by default; users hide
  // them when scheduler ticks would dominate the list. Preference persists
  // across reloads/navigation, hydrated in onMount.
  const HIDE_SCHEDULED_KEY = "argus.workflows.hideScheduled";
  let hideScheduled = $state(false);
  function setHideScheduled(value: boolean) {
    hideScheduled = value;
    try {
      localStorage.setItem(HIDE_SCHEDULED_KEY, value ? "1" : "0");
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) —
      // silently fall back to in-memory state.
    }
  }
  // Default to flat when filtering by queue — queue membership lives on
  // workflow_status, not on roots, so grouped mode would hide nested
  // queue members under un-filtered roots.
  let grouped = $state(true);
  let groupedInitFromQueue = false;
  let columns = $state<Record<ColumnKey, boolean>>({
    name: true,
    status: true,
    workflow_id: true,
    started: true,
    executor_id: true,
    queue_name: false,
  });

  const COLUMN_LABELS: Record<ColumnKey, string> = {
    name: "Name",
    status: "Status",
    workflow_id: "Workflow ID",
    started: "Started",
    executor_id: "Executor",
    queue_name: "Queue",
  };
  const REQUIRED_COLUMNS: ReadonlySet<ColumnKey> = new Set(["name", "status"]);

  function toggleStatus(value: string) {
    const next = new Set(selectedStatuses);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    selectedStatuses = next;
  }

  function buildMainParams(): Record<string, unknown> {
    const p: Record<string, unknown> = {
      grouped,
      hide_scheduled: hideScheduled,
    };
    if (filters.q.trim()) p.q = filters.q.trim();
    if (queueName) p.queue_name = queueName;
    const tz = getLocalTimeZone();
    if (dateRange.start) {
      p.started_after = dateRange.start.toDate(tz).toISOString();
    }
    if (dateRange.end) {
      const end = dateRange.end.toDate(tz);
      end.setHours(23, 59, 59, 999);
      p.started_before = end.toISOString();
    }
    if (selectedStatuses.size > 0 && selectedStatuses.size < STATUS_OPTIONS.length) {
      p.status = Array.from(selectedStatuses);
    }
    return p;
  }

  function buildEnqueuedParams(): Record<string, unknown> {
    // The strip is a top-of-page "what's currently waiting to run" pin and is
    // intentionally independent of the toolbar filters below it. The only
    // input it honors is the URL `queue_name` route scope — when the page is
    // scoped to a single queue, the strip is too.
    const p: Record<string, unknown> = {
      grouped: false,
      limit: 50,
      status: ["ENQUEUED"],
    };
    if (queueName) p.queue_name = queueName;
    return p;
  }

  function applyMainSnapshot(data: unknown): void {
    if (Array.isArray(data)) {
      workflows = data as Workflow[];
      error = null;
    }
  }
  function applyEnqueuedSnapshot(data: unknown): void {
    if (Array.isArray(data)) {
      enqueued = data as Workflow[];
      // Cache empties too: a drained queue has to seed the next visit as
      // "no strip", not leave the last non-empty snapshot standing.
      enqueuedCache.set(queueName, { rows: enqueued, at: Date.now() });
    }
  }
  function applyQueuesSnapshot(data: unknown): void {
    if (Array.isArray(data)) {
      queueList = (data as { name: string }[]).map((q) => q.name);
    }
  }

  // Filter changes flow through update_params, not new subscriptions —
  // keeps the same poller alive on the server when only one knob moved.
  // 250ms debounce coalesces bursty change events (e.g. selecting multiple
  // statuses in a popover) into a single round-trip.
  let updateDebounce: ReturnType<typeof setTimeout> | undefined;
  function scheduleParamUpdate() {
    if (updateDebounce) clearTimeout(updateDebounce);
    updateDebounce = setTimeout(() => {
      // selectedStatuses === empty set means "show nothing" client-side
      // (rather than "no filter" which the server would interpret as all).
      // Track that locally; don't push an impossible filter to the server.
      if (selectedStatuses.size === 0) {
        workflows = [];
      }
      mainHandle?.updateParams(buildMainParams());
      enqueuedHandle?.updateParams(buildEnqueuedParams());
    }, 250);
  }

  // Re-evaluate subscription params whenever any filter/view dimension changes.
  $effect(() => {
    filters.q;
    dateRange.start;
    dateRange.end;
    selectedStatuses;
    hideScheduled;
    grouped;
    queueName;
    scheduleParamUpdate();
  });

  $effect(() => {
    // First time we observe a queue filter from the URL, switch to flat view.
    if (queueName && !groupedInitFromQueue) {
      groupedInitFromQueue = true;
      grouped = false;
    }
  });

  onMount(() => {
    try {
      const storedCollapsed = localStorage.getItem(ENQUEUED_COLLAPSED_KEY);
      if (storedCollapsed !== null) enqueuedCollapsed = storedCollapsed === "1";
      hideScheduled = localStorage.getItem(HIDE_SCHEDULED_KEY) === "1";
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) — fall back
      // to defaults.
    }
    mainHandle = realtimeClient.subscribe("workflows", buildMainParams(), {
      onSnapshot: applyMainSnapshot,
      onUpdate: applyMainSnapshot,
      onError: (_code, message) => {
        error = message;
      },
    });
    enqueuedHandle = realtimeClient.subscribe("workflows", buildEnqueuedParams(), {
      onSnapshot: applyEnqueuedSnapshot,
      onUpdate: applyEnqueuedSnapshot,
    });
    queuesHandle = realtimeClient.subscribe("queues", undefined, {
      onSnapshot: applyQueuesSnapshot,
      onUpdate: applyQueuesSnapshot,
    });
  });

  // Reveal for the enqueued strip. `slide` alone would animate the strip's own
  // box but not the 16px flex gap the parent adds for it, so a third of the
  // movement would still land in one frame; growing a negative bottom margin
  // alongside the height absorbs that gap and the page below moves as one
  // block. Reduced motion returns a 0ms transition rather than needing a
  // separate code path.
  function stripReveal(node: HTMLElement) {
    if (prefersReducedMotion.current) return { duration: 0 };
    const height = parseFloat(getComputedStyle(node).height);
    const gap = node.parentElement
      ? parseFloat(getComputedStyle(node.parentElement).rowGap) || 0
      : 0;
    return {
      duration: 220,
      easing: cubicOut,
      css: (t: number) =>
        `height: ${t * height}px; margin-bottom: ${(t - 1) * gap}px; overflow: hidden;`,
    };
  }

  function toggleEnqueuedCollapsed() {
    enqueuedCollapsed = !enqueuedCollapsed;
    try {
      localStorage.setItem(ENQUEUED_COLLAPSED_KEY, enqueuedCollapsed ? "1" : "0");
    } catch {
      // see onMount note
    }
  }

  onDestroy(() => {
    mainHandle?.dispose();
    enqueuedHandle?.dispose();
    queuesHandle?.dispose();
    if (updateDebounce) clearTimeout(updateDebounce);
    if (qDebounce) clearTimeout(qDebounce);
  });

  function clearFilters() {
    qInput = "";
    filters.q = "";
    dateRange = { start: undefined, end: undefined };
    selectedStatuses = allStatuses();
    setHideScheduled(false);
    if (queueName) setQueueFilter("");
  }

  // The queue scope lives in the URL — the queues page deep-links here with
  // the same param — so selecting a queue routes through navigation rather
  // than local state.
  function setQueueFilter(name: string) {
    queuePopoverOpen = false;
    goto(name ? `#/workflows/?queue_name=${encodeURIComponent(name)}` : "#/workflows/", {
      noScroll: true,
      keepFocus: true,
    });
  }

  const statusNarrowed = $derived(
    selectedStatuses.size > 0 && selectedStatuses.size < STATUS_OPTIONS.length,
  );

  const hasActiveFilters = $derived(
    !!(
      filters.q.trim() ||
      dateRange.start ||
      dateRange.end ||
      statusNarrowed ||
      hideScheduled ||
      queueName
    ),
  );

  const rows = $derived.by<TreeRow[]>(() => {
    if (!workflows) return [];
    if (!grouped) return workflows.map((w) => ({ ...w, lineage: [] }));
    return computeLineage(workflows);
  });

  // Parallel array: groupIndex per row. In grouped mode every row sharing
  // a root (depth === 0 boundary) gets the same index, so zebra striping
  // alternates between groups instead of between sibling rows.
  const groupIndexes = $derived.by<number[]>(() => {
    const out: number[] = [];
    let g = -1;
    for (let i = 0; i < rows.length; i++) {
      if (!grouped || rows[i].depth === 0) g++;
      out.push(g);
    }
    return out;
  });

  // Case-insensitive substring split; returns alternating non-match/match
  // segments so the renderer can wrap the matches in <mark>. Matches the
  // backend's ILIKE '%q%' semantics — no regex / wildcards on the client.
  const searchTerm = $derived(filters.q.trim());
  function highlightSegments(
    text: string | null,
    query: string,
  ): { text: string; match: boolean }[] {
    if (!text) return [];
    if (!query) return [{ text, match: false }];
    const lower = text.toLowerCase();
    const q = query.toLowerCase();
    const i = lower.indexOf(q);
    if (i < 0) return [{ text, match: false }];
    return [
      { text: text.slice(0, i), match: false },
      { text: text.slice(i, i + q.length), match: true },
      { text: text.slice(i + q.length), match: false },
    ];
  }

  function formatRelative(iso: string): string {
    const then = new Date(iso).getTime();
    const diff = Date.now() - then;
    const s = Math.round(diff / 1000);
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    const m = Math.round(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.round(h / 24);
    return `${d}d ago`;
  }
</script>

{#snippet highlighted(text: string | null, query: string)}{#each highlightSegments(text, query) as part, i (i)}{#if part.match}<mark class="bg-highlight/40 text-highlight-foreground dark:bg-highlight/30 rounded-sm">{part.text}</mark>{:else}{part.text}{/if}{/each}{/snippet}

<div class="flex flex-col gap-4 p-4 pt-0 pr-3 md:p-5 md:pt-0 md:pr-3">
  {#if stripVisible}
    <div
      class="border-status-queued/30 bg-status-queued/5 overflow-hidden rounded-lg border"
      transition:stripReveal
    >
      <button
        type="button"
        onclick={toggleEnqueuedCollapsed}
        aria-expanded={!enqueuedCollapsed}
        aria-controls="enqueued-list"
        class="text-status-queued hover:bg-status-queued/10 flex w-full items-center gap-2 px-4 py-2 text-xs font-medium tracking-wide uppercase transition-colors {enqueuedCollapsed
          ? ''
          : 'border-status-queued/20 border-b'}"
      >
        <span class="bg-status-queued inline-block h-2 w-2 animate-pulse rounded-full"></span>
        Enqueued
        <span class="text-status-queued/70 normal-case tracking-normal">
          {!queueName && statsState.data && statsState.data.enqueued > enqueued.length
            ? statsState.data.enqueued
            : enqueued.length} waiting to run
        </span>
        <ChevronDownIcon
          class="ml-auto h-4 w-4 transition-transform duration-200 {enqueuedCollapsed
            ? '-rotate-90'
            : ''}"
        />
      </button>
      {#if !enqueuedCollapsed}
        <div id="enqueued-list" transition:slide={{ duration: 200 }}>
          <table class="w-full text-left text-sm">
            <thead>
              <tr
                class="border-status-queued/15 text-status-queued/70 border-b text-xs font-medium tracking-wide uppercase"
              >
                <th class="px-4 py-1.5 font-medium">Queue</th>
                <th class="px-4 py-1.5 text-right font-medium" title="Lower runs first">
                  Prio
                </th>
                <th class="px-4 py-1.5 font-medium">Name</th>
                <th class="px-4 py-1.5 font-medium">Workflow ID</th>
                <th class="px-4 py-1.5 text-right font-medium">Enqueued</th>
              </tr>
            </thead>
            <tbody>
              {#each enqueued as w (w.workflow_id)}
                {@const isScheduled = w.workflow_id.startsWith("sched-")}
                <tr
                  class="hover:bg-status-queued/10 border-status-queued/15 border-t first:border-t-0"
                >
                  <td class="w-1 px-4 py-1.5 whitespace-nowrap">
                    {#if w.queue_name}
                      <a
                        href="#/workflows/?queue_name={encodeURIComponent(w.queue_name)}"
                        class="text-status-queued font-mono text-xs hover:underline"
                        title="Filter by queue {w.queue_name}"
                      >
                        {w.queue_name}
                      </a>
                    {:else}
                      <span class="text-muted-foreground text-xs">—</span>
                    {/if}
                  </td>
                  <td class="text-muted-foreground w-1 px-4 py-1.5 text-right font-mono text-xs whitespace-nowrap">
                    {w.priority}
                  </td>
                  <td class="px-4 py-1.5 font-mono">
                    <span class="inline-flex items-center gap-1.5">
                      {#if isScheduled}
                        <CalendarClockIcon
                          class="text-status-queued size-3.5 shrink-0"
                          aria-label="Scheduled workflow"
                        />
                      {/if}
                      <a
                        href="#/workflows/{encodeURIComponent(w.workflow_id)}/"
                        class="hover:underline"
                        title={isScheduled ? "Scheduled (cron) firing" : undefined}
                      >
                        {w.name ?? "—"}
                      </a>
                    </span>
                  </td>
                  <td class="text-muted-foreground px-4 py-1.5 font-mono text-xs">
                    <a
                      href="#/workflows/{encodeURIComponent(w.workflow_id)}/"
                      class="hover:text-foreground hover:underline"
                      title={w.workflow_id}
                    >
                      {w.workflow_id}
                    </a>
                  </td>
                  <td
                    class="text-muted-foreground px-4 py-1.5 text-right text-xs"
                    title={w.started_at}
                  >
                    {formatRelative(w.started_at)}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  {/if}

  <!-- One text step smaller and slightly tighter padding than the controls ship
       with; the selectors out-rank the components' own classes. Padding targets
       direct children only so nested buttons (checkboxes, the queue chip's X)
       keep their geometry. -->
  <div
    class="flex flex-wrap items-center gap-2 [&_button]:text-xs [&_input]:text-xs [&>button]:h-8 [&>button]:px-2.5"
  >
    <InputGroup.Root class="h-8 w-full sm:w-96">
      <InputGroup.Addon>
        <SearchIcon />
      </InputGroup.Addon>
      <InputGroup.Input
        class="h-8"
        type="search"
        name="workflow-search"
        placeholder="Workflow name or ID"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="off"
        spellcheck="false"
        data-form-type="other"
        data-1p-ignore
        data-lpignore="true"
        bind:value={qInput}
      />
    </InputGroup.Root>

    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>
            <FilterIcon />
            Status
            <span class="text-muted-foreground font-normal">
              {selectedStatuses.size === 0
                ? "None"
                : selectedStatuses.size === STATUS_OPTIONS.length
                  ? "All"
                  : selectedStatuses.size}
            </span>
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-52 gap-0.5 p-1">
        {@const allSelected = selectedStatuses.size === STATUS_OPTIONS.length}
        <div class="border-border mb-1 border-b pb-1">
          <label
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none"
          >
            <Checkbox
              checked={allSelected}
              indeterminate={!allSelected && selectedStatuses.size > 0}
              onCheckedChange={() =>
                (selectedStatuses = allSelected ? new Set() : allStatuses())}
            />
            All statuses
          </label>
        </div>
        {#each STATUS_OPTIONS as opt (opt.value)}
          {@const checked = selectedStatuses.has(opt.value)}
          <label
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none"
          >
            <Checkbox {checked} onCheckedChange={() => toggleStatus(opt.value)} />
            {opt.label}
          </label>
        {/each}
      </Popover.Content>
    </Popover.Root>

    <DateRangePicker bind:value={dateRange} placeholder="Started" />

    <Popover.Root bind:open={queuePopoverOpen}>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>
            <LayersIcon />
            Queue
            <span class="text-muted-foreground max-w-32 truncate font-normal">
              {queueName || "All"}
            </span>
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-52 gap-0.5 p-1">
        <div class="border-border mb-1 border-b pb-1">
          <button
            type="button"
            onclick={() => setQueueFilter("")}
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none"
          >
            All queues
            {#if !queueName}
              <CheckIcon class="text-primary ml-auto size-4" />
            {/if}
          </button>
        </div>
        {#each queueList as name (name)}
          <button
            type="button"
            onclick={() => setQueueFilter(name)}
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none"
          >
            <span class="truncate font-mono">{name}</span>
            {#if queueName === name}
              <CheckIcon class="text-primary ml-auto size-4" />
            {/if}
          </button>
        {:else}
          <div class="text-muted-foreground px-2 py-1.5 text-xs">No queues found</div>
        {/each}
      </Popover.Content>
    </Popover.Root>

    <label
      class="bg-card shadow-surface hover:bg-muted hover:text-foreground text-foreground flex h-8 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium select-none dark:hover:bg-input/30"
      title="Hide scheduled-workflow runs (workflow IDs starting with 'sched-')"
    >
      <Checkbox checked={hideScheduled} onCheckedChange={(v) => setHideScheduled(!!v)} />
      Hide scheduled
    </label>

    {#if hasActiveFilters}
      <Separator orientation="vertical" class="!h-6" />
      <Button variant="outline" onclick={clearFilters}>
        <FilterXIcon />
        Clear filters
      </Button>
    {/if}

    <ToggleGroup.Root
      class="ml-auto"
      type="single"
      variant="outline"
      value={grouped ? "grouped" : "flat"}
      onValueChange={(v) => {
        if (v) grouped = v === "grouped";
      }}
    >
      <ToggleGroup.Item value="grouped" class="h-7 px-2.5">Grouped</ToggleGroup.Item>
      <ToggleGroup.Item value="flat" class="h-7 px-2.5">Flat</ToggleGroup.Item>
    </ToggleGroup.Root>

    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          {@const optionalKeys = (Object.keys(COLUMN_LABELS) as ColumnKey[]).filter(
            (k) => !REQUIRED_COLUMNS.has(k),
          )}
          {@const selectedCount = optionalKeys.filter((k) => columns[k]).length}
          <Button variant="outline" {...props}>
            <ColumnsIcon />
            Columns
            <span class="text-muted-foreground font-normal">
              {selectedCount === 0
                ? "None"
                : selectedCount === optionalKeys.length
                  ? "All"
                  : selectedCount}
            </span>
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="end" class="w-48 gap-0.5 p-1">
        {@const optionalKeys = (Object.keys(COLUMN_LABELS) as ColumnKey[]).filter(
          (k) => !REQUIRED_COLUMNS.has(k),
        )}
        {@const allSelected = optionalKeys.every((k) => columns[k])}
        <div class="border-border mb-1 border-b pb-1">
          <label
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none"
          >
            <Checkbox
              checked={allSelected}
              indeterminate={!allSelected && optionalKeys.some((k) => columns[k])}
              onCheckedChange={() => {
                const next = !allSelected;
                for (const k of optionalKeys) columns[k] = next;
              }}
            />
            All columns
          </label>
        </div>
        {#each Object.keys(COLUMN_LABELS) as key (key)}
          {@const k = key as ColumnKey}
          {@const checked = columns[k]}
          {@const required = REQUIRED_COLUMNS.has(k)}
          <label
            class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs select-none {required
              ? 'text-muted-foreground cursor-not-allowed'
              : 'hover:bg-muted cursor-pointer'}"
          >
            <Checkbox
              {checked}
              disabled={required}
              onCheckedChange={() => (columns[k] = !columns[k])}
            />
            {COLUMN_LABELS[k]}
          </label>
        {/each}
      </Popover.Content>
    </Popover.Root>
  </div>

  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {:else if workflows === null}
    <p class="text-muted-foreground text-sm">Loading…</p>
  {:else if workflows.length === 0}
    <p class="text-muted-foreground text-sm">
      {hasActiveFilters
        ? "No workflows match the current filters."
        : enqueued.length > 0
          ? "No completed runs yet — only the enqueued workflows above."
          : "No workflows yet. Run a DBOS app pointed at this database to see data here."}
    </p>
  {:else}
    <Card.Root class="gap-0 py-0">
      <!-- Fixed layout: the metadata columns hold a set width and name/ID
           share what is left, so long values ellipsis instead of widening
           the table into a horizontal scroll. -->
      <Table.Root class="table-fixed">
        <Table.Header class="bg-muted/40 [&_th]:h-9">
          <Table.Row class="hover:bg-muted/40">
            {#if columns.name}<Table.Head class="px-4">Name</Table.Head>{/if}
            {#if columns.status}<Table.Head class="w-[104px] px-4">Status</Table.Head>{/if}
            {#if columns.workflow_id}<Table.Head class="px-4">Workflow ID</Table.Head>{/if}
            {#if columns.started}<Table.Head class="w-[92px] px-4">Started</Table.Head>{/if}
            {#if columns.executor_id}<Table.Head class="w-[132px] px-4">Executor</Table.Head>{/if}
            {#if columns.queue_name}<Table.Head class="w-[104px] px-4">Queue</Table.Head>{/if}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each rows as w, i (w.workflow_id)}
            {@const nextRow = rows[i + 1]}
            {@const continuesGroup = grouped && nextRow !== undefined && nextRow.depth > 0}
            {@const altRow = groupIndexes[i] % 2 === 1}
            <Table.Row
              onclick={(e) => {
                // Don't double-handle clicks on inner anchors — let the
                // browser navigate them natively (preserves middle-click,
                // ctrl/cmd-click, "open in new tab").
                if ((e.target as HTMLElement).closest("a")) return;
                goto(`#/workflows/${encodeURIComponent(w.workflow_id)}/`);
              }}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  goto(`#/workflows/${encodeURIComponent(w.workflow_id)}/`);
                }
              }}
              tabindex={0}
              role="link"
              class="focus:bg-muted/50 cursor-pointer outline-none {altRow
                ? 'bg-muted/30'
                : ''} {continuesGroup ? 'border-b-0' : ''}"
            >
              {#if columns.name}
                <Table.Cell class="px-4 py-0 font-mono">
                  <div class="flex min-w-0 items-stretch">
                    {#each w.lineage as hasNext, i}
                      {@const isConnector = i === w.lineage.length - 1}
                      <div class="relative w-5 flex-none self-stretch">
                        {#if isConnector}
                          <span
                            class="bg-border absolute top-0 left-1/2 h-1/2 w-px -translate-x-1/2"
                            aria-hidden="true"
                          ></span>
                          {#if hasNext}
                            <span
                              class="bg-border absolute bottom-0 left-1/2 h-1/2 w-px -translate-x-1/2"
                              aria-hidden="true"
                            ></span>
                          {/if}
                          <span
                            class="bg-border absolute top-1/2 left-1/2 h-px w-2.5 -translate-y-1/2"
                            aria-hidden="true"
                          ></span>
                        {:else if hasNext}
                          <span
                            class="bg-border absolute inset-y-0 left-1/2 w-px -translate-x-1/2"
                            aria-hidden="true"
                          ></span>
                        {/if}
                      </div>
                    {/each}
                    <a
                      href="#/workflows/{encodeURIComponent(w.workflow_id)}/"
                      title={w.name ?? ""}
                      class="truncate hover:text-foreground hover:underline {!grouped ||
                      w.depth === 0
                        ? 'py-1.5'
                        : 'py-0.5'} {grouped && w.depth > 0 ? 'pl-1' : ''}"
                    >
                      {#if w.name}{@render highlighted(w.name, searchTerm)}{:else}—{/if}
                    </a>
                  </div>
                </Table.Cell>
              {/if}
              {#if columns.status}
                <Table.Cell class="px-4 {!grouped || w.depth === 0 ? 'py-1.5' : 'py-0.5'}">
                  <Badge class={statusBadgeClass(w.status)}>{formatStatus(w.status)}</Badge>
                </Table.Cell>
              {/if}
              {#if columns.workflow_id}
                <Table.Cell
                  class="text-muted-foreground truncate px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-1.5'
                    : 'py-0.5'}"
                >
                  <a
                    href="#/workflows/{encodeURIComponent(w.workflow_id)}/"
                    title={w.workflow_id}
                    class="hover:text-foreground hover:underline"
                  >
                    {@render highlighted(w.workflow_id, searchTerm)}
                  </a>
                </Table.Cell>
              {/if}
              {#if columns.started}
                <Table.Cell
                  class="text-muted-foreground truncate px-4 {!grouped || w.depth === 0
                    ? 'py-1.5'
                    : 'py-0.5'}"
                  title={w.started_at}
                >
                  {formatRelative(w.started_at)}
                </Table.Cell>
              {/if}
              {#if columns.executor_id}
                <Table.Cell
                  class="text-muted-foreground truncate px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-1.5'
                    : 'py-0.5'}"
                  title={w.executor_id ?? ""}
                >
                  {w.executor_id ?? "—"}
                </Table.Cell>
              {/if}
              {#if columns.queue_name}
                <Table.Cell
                  class="text-muted-foreground truncate px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-1.5'
                    : 'py-0.5'}"
                  title={w.queue_name ?? ""}
                >
                  {#if w.queue_name}
                    <a
                      href="#/workflows/?queue_name={encodeURIComponent(w.queue_name)}"
                      class="hover:text-foreground hover:underline"
                    >
                      {w.queue_name}
                    </a>
                  {:else}
                    —
                  {/if}
                </Table.Cell>
              {/if}
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card.Root>
  {/if}
</div>
