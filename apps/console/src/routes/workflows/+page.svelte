<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { getLocalTimeZone, type DateValue } from "@internationalized/date";
  import FilterIcon from "@lucide/svelte/icons/list-filter";
  import SearchIcon from "@lucide/svelte/icons/search";
  import ColumnsIcon from "@lucide/svelte/icons/columns-3";
  import XIcon from "@lucide/svelte/icons/x";
  import CheckIcon from "@lucide/svelte/icons/check";
  import ListChecksIcon from "@lucide/svelte/icons/list-checks";
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import { slide } from "svelte/transition";
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
    statusBadgeClass,
    type TreeRow,
    type Workflow,
  } from "$lib/workflow-tree";
  import { STATUS_LABELS, WORKFLOW_STATUSES } from "$lib/workflow-status";
  import { breadcrumb } from "$lib/breadcrumb.svelte";

  const queueName = $derived(page.url.searchParams.get("queue_name") ?? "");

  $effect(() => {
    breadcrumb.items = queueName
      ? [
          { label: "Workflows", href: "/workflows/", icon: "workflow" },
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
  // hides them from /api/workflows by default, and the strip fetches them
  // explicitly via ?status=ENQUEUED.
  let enqueued = $state<Workflow[]>([]);
  // Collapse state survives reloads/navigation; SSR has no window so the
  // initial value defaults to expanded and gets corrected on hydrate.
  const ENQUEUED_COLLAPSED_KEY = "argus.workflows.enqueuedCollapsed";
  let enqueuedCollapsed = $state(false);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  let filters = $state({
    q: "",
  });
  let dateRange = $state<{ start: DateValue | undefined; end: DateValue | undefined }>({
    start: undefined,
    end: undefined,
  });
  // Filter options derived from the canonical status list — adding a new DBOS
  // workflow status only requires editing `$lib/workflow-status.ts`. ENQUEUED
  // is intentionally omitted: those rows live in the pinned strip above the
  // main list, not as a filterable status here.
  const STATUS_OPTIONS = WORKFLOW_STATUSES.filter((s) => s !== "ENQUEUED").map((value) => ({
    value,
    label: STATUS_LABELS[value],
  }));
  const allStatuses = () => new Set(STATUS_OPTIONS.map((o) => o.value));

  let selectedStatuses = $state<Set<string>>(allStatuses());
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

  function buildQuery(): string {
    const params = new URLSearchParams();
    if (filters.q.trim()) params.set("q", filters.q.trim());
    if (queueName) params.set("queue_name", queueName);
    const tz = getLocalTimeZone();
    if (dateRange.start) {
      params.set("started_after", dateRange.start.toDate(tz).toISOString());
    }
    if (dateRange.end) {
      const end = dateRange.end.toDate(tz);
      end.setHours(23, 59, 59, 999);
      params.set("started_before", end.toISOString());
    }
    if (selectedStatuses.size > 0 && selectedStatuses.size < STATUS_OPTIONS.length) {
      for (const s of selectedStatuses) params.append("status", s);
    }
    if (hideScheduled) params.set("hide_scheduled", "true");
    params.set("grouped", grouped ? "true" : "false");
    return params.toString();
  }

  function buildEnqueuedQuery(): string {
    // The strip is a top-of-page "what's currently waiting to run" pin and is
    // intentionally independent of the toolbar filters below it. The only
    // input it honors is the URL `queue_name` route scope — when the page is
    // scoped to a single queue, the strip is too.
    const params = new URLSearchParams();
    if (queueName) params.set("queue_name", queueName);
    params.set("status", "ENQUEUED");
    params.set("grouped", "false");
    params.set("limit", "50");
    return params.toString();
  }

  async function refresh() {
    try {
      const enqRes = await fetch("/api/workflows?" + buildEnqueuedQuery());
      if (!enqRes.ok) throw new Error(`HTTP ${enqRes.status}`);
      enqueued = (await enqRes.json()) as Workflow[];
      if (selectedStatuses.size === 0) {
        workflows = [];
      } else {
        const listRes = await fetch("/api/workflows?" + buildQuery());
        if (!listRes.ok) throw new Error(`HTTP ${listRes.status}`);
        workflows = (await listRes.json()) as Workflow[];
      }
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      workflows = null;
      enqueued = [];
    }
  }

  let debounce: ReturnType<typeof setTimeout> | undefined;
  function scheduleRefresh() {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(refresh, 250);
  }

  // Re-fetch whenever any filter/view dimension changes.
  $effect(() => {
    filters.q;
    dateRange.start;
    dateRange.end;
    selectedStatuses;
    hideScheduled;
    grouped;
    queueName;
    scheduleRefresh();
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
      enqueuedCollapsed = localStorage.getItem(ENQUEUED_COLLAPSED_KEY) === "1";
      hideScheduled = localStorage.getItem(HIDE_SCHEDULED_KEY) === "1";
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) — fall back
      // to defaults.
    }
    refresh();
    timer = setInterval(refresh, 5000);
  });

  function toggleEnqueuedCollapsed() {
    enqueuedCollapsed = !enqueuedCollapsed;
    try {
      localStorage.setItem(ENQUEUED_COLLAPSED_KEY, enqueuedCollapsed ? "1" : "0");
    } catch {
      // see onMount note
    }
  }

  onDestroy(() => {
    if (timer) clearInterval(timer);
    if (debounce) clearTimeout(debounce);
  });

  function clearFilters() {
    filters.q = "";
    dateRange = { start: undefined, end: undefined };
    selectedStatuses = allStatuses();
    setHideScheduled(false);
  }

  function clearQueueFilter() {
    goto("/workflows/");
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
      hideScheduled
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

<div class="flex flex-col gap-4 p-6">
  {#if enqueued.length > 0}
    <div
      class="border-violet-200 bg-violet-50/60 dark:border-violet-500/20 dark:bg-violet-500/5 overflow-hidden rounded-lg border"
    >
      <button
        type="button"
        onclick={toggleEnqueuedCollapsed}
        aria-expanded={!enqueuedCollapsed}
        aria-controls="enqueued-list"
        class="hover:bg-violet-100/40 dark:hover:bg-violet-500/10 flex w-full items-center gap-2 px-4 py-2 text-xs font-medium tracking-wide uppercase text-violet-700 transition-colors dark:text-violet-300 {enqueuedCollapsed
          ? ''
          : 'border-violet-200 dark:border-violet-500/20 border-b'}"
      >
        <span class="inline-block h-2 w-2 animate-pulse rounded-full bg-violet-500"></span>
        Enqueued
        <span class="text-violet-600/70 dark:text-violet-400/70 normal-case tracking-normal">
          {enqueued.length} waiting to run
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
            <tbody>
              {#each enqueued as w (w.workflow_id)}
                <tr
                  class="hover:bg-violet-100/40 dark:hover:bg-violet-500/10 border-violet-200/60 dark:border-violet-500/10 border-t first:border-t-0"
                >
                  <td class="w-1 px-4 py-1.5 whitespace-nowrap">
                    {#if w.queue_name}
                      <a
                        href="/workflows/?queue_name={encodeURIComponent(w.queue_name)}"
                        class="font-mono text-xs text-violet-700 hover:underline dark:text-violet-300"
                        title="Filter by queue {w.queue_name}"
                      >
                        {w.queue_name}
                      </a>
                    {:else}
                      <span class="text-muted-foreground text-xs">—</span>
                    {/if}
                  </td>
                  <td class="px-4 py-1.5 font-mono">
                    <a
                      href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                      class="hover:underline"
                    >
                      {w.name ?? "—"}
                    </a>
                  </td>
                  <td class="text-muted-foreground px-4 py-1.5 font-mono text-xs">
                    <a
                      href="/workflows/{encodeURIComponent(w.workflow_id)}/"
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

  <div class="flex flex-wrap items-center gap-2">
    {#if queueName}
      <Badge variant="secondary">
        Queue: <span class="font-mono">{queueName}</span>
        <button
          type="button"
          onclick={clearQueueFilter}
          class="hover:text-foreground"
          aria-label="Clear queue filter"
        >
          <XIcon />
        </button>
      </Badge>
    {/if}
    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>
            <FilterIcon />
            Status
            <Badge variant="secondary">
              {selectedStatuses.size === 0
                ? "None"
                : selectedStatuses.size === STATUS_OPTIONS.length
                  ? "All"
                  : selectedStatuses.size}
            </Badge>
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-52 gap-0.5 p-1">
        {#each STATUS_OPTIONS as opt (opt.value)}
          {@const checked = selectedStatuses.has(opt.value)}
          <button
            type="button"
            onclick={() => toggleStatus(opt.value)}
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-2xl px-2 py-1.5 text-left text-sm"
          >
            <CheckIcon class="size-4 {checked ? 'opacity-100' : 'opacity-0'}" />
            {opt.label}
          </button>
        {/each}
        {@const allSelected = selectedStatuses.size === STATUS_OPTIONS.length}
        <div class="border-border mt-1 border-t pt-1">
          <button
            type="button"
            onclick={() =>
              (selectedStatuses = allSelected ? new Set() : allStatuses())}
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-2xl px-2 py-1.5 text-left text-sm"
          >
            <ListChecksIcon class="size-4" />
            {allSelected ? "Deselect all" : "Select all"}
          </button>
        </div>
      </Popover.Content>
    </Popover.Root>

    <InputGroup.Root class="w-96">
      <InputGroup.Addon>
        <SearchIcon />
      </InputGroup.Addon>
      <InputGroup.Input
        type="text"
        placeholder="Workflow name or ID"
        bind:value={filters.q}
      />
    </InputGroup.Root>

    <DateRangePicker bind:value={dateRange} placeholder="Started" />

    <label
      class="hover:bg-muted text-foreground flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-sm select-none"
      title="Hide scheduled-workflow runs (workflow IDs starting with 'sched-')"
    >
      <Checkbox checked={hideScheduled} onCheckedChange={(v) => setHideScheduled(!!v)} />
      Hide scheduled
    </label>

    {#if hasActiveFilters}
      <Separator orientation="vertical" class="!h-6" />
      <Button variant="ghost" onclick={clearFilters}>Clear filters</Button>
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
      <ToggleGroup.Item value="grouped">Grouped</ToggleGroup.Item>
      <ToggleGroup.Item value="flat">Flat</ToggleGroup.Item>
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
            <Badge variant="secondary">
              {selectedCount === 0
                ? "None"
                : selectedCount === optionalKeys.length
                  ? "All"
                  : selectedCount}
            </Badge>
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="end" class="w-48 gap-0.5 p-1">
        {#each Object.keys(COLUMN_LABELS) as key (key)}
          {@const k = key as ColumnKey}
          {@const checked = columns[k]}
          {@const required = REQUIRED_COLUMNS.has(k)}
          <button
            type="button"
            disabled={required}
            onclick={() => (columns[k] = !columns[k])}
            class="flex w-full items-center gap-2 rounded-2xl px-2 py-1.5 text-left text-sm {required
              ? 'text-muted-foreground cursor-not-allowed'
              : 'hover:bg-muted cursor-pointer'}"
          >
            <CheckIcon class="size-4 {checked ? 'opacity-100' : 'opacity-0'}" />
            {COLUMN_LABELS[k]}
          </button>
        {/each}
        {@const optionalKeys = (Object.keys(COLUMN_LABELS) as ColumnKey[]).filter(
          (k) => !REQUIRED_COLUMNS.has(k),
        )}
        {@const allSelected = optionalKeys.every((k) => columns[k])}
        <div class="border-border mt-1 border-t pt-1">
          <button
            type="button"
            onclick={() => {
              const next = !allSelected;
              for (const k of optionalKeys) columns[k] = next;
            }}
            class="hover:bg-muted flex w-full cursor-pointer items-center gap-2 rounded-2xl px-2 py-1.5 text-left text-sm"
          >
            <ListChecksIcon class="size-4" />
            {allSelected ? "Deselect all" : "Select all"}
          </button>
        </div>
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
      {hasActiveFilters || queueName
        ? "No workflows match the current filters."
        : enqueued.length > 0
          ? "No completed runs yet — only the enqueued workflows above."
          : "No workflows yet. Run a DBOS app pointed at this database to see data here."}
    </p>
  {:else}
    <Card.Root class="gap-0 py-0 shadow-xs">
      <Table.Root>
        <Table.Header class="bg-muted/40">
          <Table.Row class="hover:bg-muted/40">
            {#if columns.name}<Table.Head class="px-4">Name</Table.Head>{/if}
            {#if columns.status}<Table.Head class="px-4">Status</Table.Head>{/if}
            {#if columns.workflow_id}<Table.Head class="px-4">Workflow ID</Table.Head>{/if}
            {#if columns.started}<Table.Head class="px-4">Started</Table.Head>{/if}
            {#if columns.executor_id}<Table.Head class="px-4">Executor</Table.Head>{/if}
            {#if columns.queue_name}<Table.Head class="px-4">Queue</Table.Head>{/if}
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
                goto(`/workflows/${encodeURIComponent(w.workflow_id)}/`);
              }}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  goto(`/workflows/${encodeURIComponent(w.workflow_id)}/`);
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
                  <div class="flex items-stretch">
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
                      href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                      class="hover:text-foreground hover:underline {!grouped || w.depth === 0
                        ? 'py-2'
                        : 'py-1'} {grouped && w.depth > 0 ? 'pl-1' : ''}"
                    >
                      {w.name ?? "—"}
                    </a>
                  </div>
                </Table.Cell>
              {/if}
              {#if columns.status}
                <Table.Cell class="px-4 {!grouped || w.depth === 0 ? 'py-2' : 'py-1'}">
                  <Badge class={statusBadgeClass(w.status)}>{w.status ?? "—"}</Badge>
                </Table.Cell>
              {/if}
              {#if columns.workflow_id}
                <Table.Cell
                  class="text-muted-foreground px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                >
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    title={w.workflow_id}
                    class="hover:text-foreground hover:underline"
                  >
                    {w.workflow_id}
                  </a>
                </Table.Cell>
              {/if}
              {#if columns.started}
                <Table.Cell
                  class="text-muted-foreground px-4 {!grouped || w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.started_at}
                >
                  {formatRelative(w.started_at)}
                </Table.Cell>
              {/if}
              {#if columns.executor_id}
                <Table.Cell
                  class="text-muted-foreground px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.executor_id ?? ""}
                >
                  {w.executor_id ?? "—"}
                </Table.Cell>
              {/if}
              {#if columns.queue_name}
                <Table.Cell
                  class="text-muted-foreground px-4 font-mono text-xs {!grouped ||
                  w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.queue_name ?? ""}
                >
                  {#if w.queue_name}
                    <a
                      href="/workflows/?queue_name={encodeURIComponent(w.queue_name)}"
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
