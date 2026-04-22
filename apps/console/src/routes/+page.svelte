<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { Popover, Switch } from "bits-ui";
  import { getLocalTimeZone, type DateValue } from "@internationalized/date";
  import DateRangePicker from "$lib/components/DateRangePicker.svelte";

  type Workflow = {
    workflow_id: string;
    parent_workflow_id: string | null;
    name: string | null;
    status: string | null;
    started_at: string;
    updated_at: string;
    depth: number;
  };

  // For each row, a `lineage` array of booleans of length == depth.
  // Entry at index i (i < depth-1) says "draw vertical line at this column"
  // (true) vs "empty space" (false) based on whether the ancestor at depth
  // i+1 has a next sibling. Entry at index depth-1 (the row's own connector
  // column) is true for ├─ and false for └─.
  type TreeRow = Workflow & { lineage: boolean[] };

  type ColumnKey = "status" | "workflow_id" | "name" | "started" | "updated";

  let workflows = $state<Workflow[] | null>(null);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  let filters = $state({
    workflow_id: "",
    name: "",
  });
  let dateRange = $state<{ start: DateValue | undefined; end: DateValue | undefined }>({
    start: undefined,
    end: undefined,
  });
  let selectedStatuses = $state<Set<string>>(new Set());
  let grouped = $state(true);
  let columns = $state<Record<ColumnKey, boolean>>({
    status: true,
    workflow_id: true,
    name: true,
    started: true,
    updated: true,
  });

  const COLUMN_LABELS: Record<ColumnKey, string> = {
    status: "Status",
    workflow_id: "Workflow ID",
    name: "Name",
    started: "Started",
    updated: "Updated",
  };

  const STATUS_OPTIONS: { value: string; label: string }[] = [
    { value: "PENDING", label: "Pending" },
    { value: "ENQUEUED", label: "Enqueued" },
    { value: "RUNNING", label: "Running" },
    { value: "SUCCESS", label: "Success" },
    { value: "ERROR", label: "Error" },
    { value: "CANCELLED", label: "Cancelled" },
    { value: "MAX_RECOVERY_ATTEMPTS_EXCEEDED", label: "Max retries" },
  ];

  function toggleStatus(value: string) {
    const next = new Set(selectedStatuses);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    selectedStatuses = next;
  }

  function buildQuery(): string {
    const params = new URLSearchParams();
    if (filters.workflow_id.trim()) params.set("workflow_id", filters.workflow_id.trim());
    if (filters.name.trim()) params.set("name", filters.name.trim());
    const tz = getLocalTimeZone();
    if (dateRange.start) {
      params.set("started_after", dateRange.start.toDate(tz).toISOString());
    }
    if (dateRange.end) {
      const end = dateRange.end.toDate(tz);
      end.setHours(23, 59, 59, 999);
      params.set("started_before", end.toISOString());
    }
    for (const s of selectedStatuses) params.append("status", s);
    params.set("grouped", grouped ? "true" : "false");
    return params.toString();
  }

  async function refresh() {
    try {
      const res = await fetch("/api/workflows?" + buildQuery());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      workflows = (await res.json()) as Workflow[];
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      workflows = null;
    }
  }

  let debounce: ReturnType<typeof setTimeout> | undefined;
  function scheduleRefresh() {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(refresh, 250);
  }

  // Re-fetch whenever any filter/view dimension changes.
  $effect(() => {
    filters.workflow_id;
    filters.name;
    dateRange.start;
    dateRange.end;
    selectedStatuses;
    grouped;
    scheduleRefresh();
  });

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
    if (debounce) clearTimeout(debounce);
  });

  function clearFilters() {
    filters.workflow_id = "";
    filters.name = "";
    dateRange = { start: undefined, end: undefined };
    selectedStatuses = new Set();
  }

  const hasActiveFilters = $derived(
    !!(
      filters.workflow_id.trim() ||
      filters.name.trim() ||
      dateRange.start ||
      dateRange.end ||
      selectedStatuses.size
    ),
  );

  const rows = $derived.by<TreeRow[]>(() => {
    if (!workflows) return [];
    if (!grouped) return workflows.map((w) => ({ ...w, lineage: [] }));

    const byId = new Map(workflows.map((w) => [w.workflow_id, w]));

    // Rows arrive in DFS order: for each row R, scan forward — the first row
    // with depth <= R.depth is either R's next sibling (depth ==) or breaks
    // out of R's subtree (depth <).
    const hasNext = new Map<string, boolean>();
    for (let i = 0; i < workflows.length; i++) {
      const r = workflows[i];
      let flag = false;
      for (let j = i + 1; j < workflows.length; j++) {
        const q = workflows[j];
        if (q.depth < r.depth) break;
        if (q.depth === r.depth) {
          flag = q.parent_workflow_id === r.parent_workflow_id;
          break;
        }
      }
      hasNext.set(r.workflow_id, flag);
    }

    return workflows.map((w) => {
      // chain = [rootAncestor, ..., parent, w] ordered by increasing depth.
      const chain: Workflow[] = [w];
      let cur: Workflow | undefined = w;
      while (cur?.parent_workflow_id) {
        const p = byId.get(cur.parent_workflow_id);
        if (!p) break;
        chain.unshift(p);
        cur = p;
      }
      const lineage: boolean[] = [];
      for (let i = 0; i < w.depth; i++) {
        const ancestor = chain[i + 1];
        lineage.push(hasNext.get(ancestor.workflow_id) ?? false);
      }
      return { ...w, lineage };
    });
  });

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

  function statusClass(status: string | null): string {
    const s = (status ?? "").toUpperCase();
    if (s === "SUCCESS")
      return "bg-green-100 text-green-800 ring-green-600/20";
    if (s === "PENDING" || s === "RUNNING" || s === "ENQUEUED")
      return "bg-blue-100 text-blue-800 ring-blue-600/20";
    if (s === "ERROR" || s === "CANCELLED" || s === "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
      return "bg-red-100 text-red-800 ring-red-600/20";
    return "bg-neutral-100 text-neutral-700 ring-neutral-400/20";
  }

  function statusDotClass(status: string): string {
    if (status === "SUCCESS") return "bg-green-500";
    if (status === "PENDING" || status === "RUNNING" || status === "ENQUEUED") return "bg-blue-500";
    if (status === "ERROR" || status === "CANCELLED" || status === "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
      return "bg-red-500";
    return "bg-neutral-400";
  }
</script>

<div class="flex flex-col gap-4 p-6">
  <h1 class="text-2xl font-semibold">Workflows</h1>

  <div class="flex flex-wrap items-center gap-2">
    <Popover.Root>
      <Popover.Trigger
        class="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-xs hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-400 data-[state=open]:bg-neutral-50"
      >
        <svg class="h-4 w-4 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6h18M6 12h12M10 18h4" />
        </svg>
        Status
        {#if selectedStatuses.size > 0}
          <span class="ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-neutral-900 px-1.5 text-[11px] font-medium text-white">
            {selectedStatuses.size}
          </span>
        {/if}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="start"
          class="z-20 w-52 rounded-lg border border-neutral-200 bg-white p-1 shadow-lg outline-none"
        >
          {#each STATUS_OPTIONS as opt (opt.value)}
            {@const checked = selectedStatuses.has(opt.value)}
            <label class="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-neutral-100">
              <input
                type="checkbox"
                {checked}
                onchange={() => toggleStatus(opt.value)}
                class="h-4 w-4 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-400"
              />
              <span class="flex items-center gap-1.5">
                <span class="inline-block h-2 w-2 rounded-full {statusDotClass(opt.value)}"></span>
                {opt.label}
              </span>
            </label>
          {/each}
          {#if selectedStatuses.size > 0}
            <div class="border-t border-neutral-200 p-1">
              <button
                type="button"
                onclick={() => (selectedStatuses = new Set())}
                class="w-full rounded-md px-2 py-1 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
              >
                Clear
              </button>
            </div>
          {/if}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>

    <div class="relative">
      <svg
        class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4-4m0 0a7 7 0 10-9.9 0 7 7 0 009.9 0z" />
      </svg>
      <input
        type="text"
        placeholder="Workflow ID"
        bind:value={filters.workflow_id}
        class="w-52 rounded-md border border-neutral-300 bg-white py-1.5 pl-8 pr-3 text-sm shadow-xs placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none focus:ring-2 focus:ring-neutral-400"
      />
    </div>
    <div class="relative">
      <svg
        class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h8" />
      </svg>
      <input
        type="text"
        placeholder="Name (wildcard)"
        bind:value={filters.name}
        class="w-52 rounded-md border border-neutral-300 bg-white py-1.5 pl-8 pr-3 text-sm shadow-xs placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none focus:ring-2 focus:ring-neutral-400"
      />
    </div>

    <DateRangePicker bind:value={dateRange} placeholder="Started" />

    {#if hasActiveFilters}
      <button
        type="button"
        onclick={clearFilters}
        class="rounded-md px-2 py-1.5 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
      >
        Clear filters
      </button>
    {/if}

    <div class="ml-auto flex items-center gap-3">
      <label class="flex cursor-pointer items-center gap-2 text-sm text-neutral-700 select-none">
        <Switch.Root
          bind:checked={grouped}
          class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent transition-colors data-[state=checked]:bg-neutral-900 data-[state=unchecked]:bg-neutral-300 focus:outline-none focus:ring-2 focus:ring-neutral-400 focus:ring-offset-1"
        >
          <Switch.Thumb
            class="pointer-events-none block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]"
          />
        </Switch.Root>
        Group workflows
      </label>

      <Popover.Root>
        <Popover.Trigger
          class="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-xs hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-400 data-[state=open]:bg-neutral-50"
        >
          <svg class="h-4 w-4 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 4v16M16 4v16" />
          </svg>
          Columns
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            sideOffset={6}
            align="end"
            class="z-20 w-48 rounded-lg border border-neutral-200 bg-white p-1 shadow-lg outline-none"
          >
            {#each Object.keys(COLUMN_LABELS) as key (key)}
              <label class="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-neutral-100">
                <input
                  type="checkbox"
                  bind:checked={columns[key as ColumnKey]}
                  class="h-4 w-4 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-400"
                />
                {COLUMN_LABELS[key as ColumnKey]}
              </label>
            {/each}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  </div>

  {#if error}
    <div class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {error}
    </div>
  {:else if workflows === null}
    <p class="text-sm text-neutral-500">Loading…</p>
  {:else if workflows.length === 0}
    <p class="text-sm text-neutral-500">
      {hasActiveFilters
        ? "No workflows match the current filters."
        : "No workflows yet. Run a DBOS app pointed at this database to see data here."}
    </p>
  {:else}
    <div class="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-xs">
      <table class="w-full text-left text-sm">
        <thead class="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            {#if columns.status}<th class="px-4 py-2 font-medium">Status</th>{/if}
            {#if columns.workflow_id}<th class="px-4 py-2 font-medium">Workflow ID</th>{/if}
            {#if columns.name}<th class="px-4 py-2 font-medium">Name</th>{/if}
            {#if columns.started}<th class="px-4 py-2 font-medium">Started</th>{/if}
            {#if columns.updated}<th class="px-4 py-2 font-medium">Updated</th>{/if}
          </tr>
        </thead>
        <tbody>
          {#each rows as w (w.workflow_id)}
            <tr
              class="{grouped && w.depth === 0
                ? 'border-t border-neutral-200'
                : !grouped
                  ? 'border-t border-neutral-200'
                  : ''} hover:bg-neutral-50"
            >
              {#if columns.status}
                <td class="px-4 {!grouped || w.depth === 0 ? 'py-2' : 'py-1'}">
                  <span
                    class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset {statusClass(
                      w.status,
                    )}"
                  >
                    {w.status ?? "—"}
                  </span>
                </td>
              {/if}
              {#if columns.workflow_id}
                <td
                  class="px-4 font-mono text-xs text-neutral-500 {!grouped ||
                  w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.workflow_id}>{w.workflow_id}</td
                >
              {/if}
              {#if columns.name}
                <td class="px-4 py-0 font-mono">
                  <div class="flex items-stretch">
                    {#each w.lineage as hasNext, i}
                      {@const isConnector = i === w.lineage.length - 1}
                      <div class="relative w-5 flex-none self-stretch">
                        {#if isConnector}
                          <span
                            class="absolute left-1/2 top-0 h-1/2 w-px -translate-x-1/2 bg-neutral-300"
                            aria-hidden="true"
                          ></span>
                          {#if hasNext}
                            <span
                              class="absolute bottom-0 left-1/2 h-1/2 w-px -translate-x-1/2 bg-neutral-300"
                              aria-hidden="true"
                            ></span>
                          {/if}
                          <span
                            class="absolute left-1/2 top-1/2 h-px w-2.5 -translate-y-1/2 bg-neutral-300"
                            aria-hidden="true"
                          ></span>
                        {:else if hasNext}
                          <span
                            class="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-neutral-300"
                            aria-hidden="true"
                          ></span>
                        {/if}
                      </div>
                    {/each}
                    <span
                      class="{!grouped || w.depth === 0
                        ? 'py-2'
                        : 'py-1'} {grouped && w.depth > 0
                        ? 'pl-1'
                        : ''}">{w.name ?? "—"}</span
                    >
                  </div>
                </td>
              {/if}
              {#if columns.started}
                <td
                  class="px-4 text-neutral-600 {!grouped || w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.started_at}
                >
                  {formatRelative(w.started_at)}
                </td>
              {/if}
              {#if columns.updated}
                <td
                  class="px-4 text-neutral-600 {!grouped || w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.updated_at}
                >
                  {formatRelative(w.updated_at)}
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
