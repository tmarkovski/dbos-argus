<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { getLocalTimeZone, type DateValue } from "@internationalized/date";
  import FilterIcon from "@lucide/svelte/icons/list-filter";
  import SearchIcon from "@lucide/svelte/icons/search";
  import TextIcon from "@lucide/svelte/icons/text";
  import ColumnsIcon from "@lucide/svelte/icons/columns-3";
  import DateRangePicker from "$lib/components/DateRangePicker.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Badge } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Popover from "$lib/components/ui/popover";
  import {
    computeLineage,
    statusBadgeClass,
    type TreeRow,
    type Workflow,
  } from "$lib/workflow-tree";
  import { breadcrumb } from "$lib/breadcrumb.svelte";

  $effect(() => {
    breadcrumb.items = [{ label: "Home" }];
    return () => {
      breadcrumb.items = [];
    };
  });

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
  const STATUS_OPTIONS: { value: string; label: string }[] = [
    { value: "PENDING", label: "Pending" },
    { value: "ENQUEUED", label: "Enqueued" },
    { value: "DELAYED", label: "Delayed" },
    { value: "SUCCESS", label: "Success" },
    { value: "ERROR", label: "Error" },
    { value: "CANCELLED", label: "Cancelled" },
    { value: "MAX_RECOVERY_ATTEMPTS_EXCEEDED", label: "Max retries" },
  ];
  const allStatuses = () => new Set(STATUS_OPTIONS.map((o) => o.value));

  let selectedStatuses = $state<Set<string>>(allStatuses());
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
    if (selectedStatuses.size > 0 && selectedStatuses.size < STATUS_OPTIONS.length) {
      for (const s of selectedStatuses) params.append("status", s);
    }
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
    selectedStatuses = allStatuses();
  }

  const statusNarrowed = $derived(
    selectedStatuses.size > 0 && selectedStatuses.size < STATUS_OPTIONS.length,
  );

  const hasActiveFilters = $derived(
    !!(
      filters.workflow_id.trim() ||
      filters.name.trim() ||
      dateRange.start ||
      dateRange.end ||
      statusNarrowed
    ),
  );

  const rows = $derived.by<TreeRow[]>(() => {
    if (!workflows) return [];
    if (!grouped) return workflows.map((w) => ({ ...w, lineage: [] }));
    return computeLineage(workflows);
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

  function statusDotClass(status: string): string {
    if (status === "SUCCESS") return "bg-green-500";
    if (status === "PENDING" || status === "ENQUEUED" || status === "DELAYED") return "bg-blue-500";
    if (status === "CANCELLED") return "bg-amber-500";
    if (status === "ERROR" || status === "MAX_RECOVERY_ATTEMPTS_EXCEEDED") return "bg-red-500";
    return "bg-muted-foreground/50";
  }
</script>

<div class="flex flex-col gap-4 p-6">
  <div class="flex flex-wrap items-center gap-2">
    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>
            <FilterIcon />
            Status
            {#if statusNarrowed}
              <Badge variant="secondary" class="ml-1 h-4 min-w-4 px-1 text-[10px]">
                {selectedStatuses.size}
              </Badge>
            {/if}
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-52 p-1">
        {#each STATUS_OPTIONS as opt (opt.value)}
          {@const checked = selectedStatuses.has(opt.value)}
          <label class="hover:bg-muted flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm">
            <Checkbox {checked} onCheckedChange={() => toggleStatus(opt.value)} />
            <span class="flex items-center gap-1.5">
              <span class="inline-block h-2 w-2 rounded-full {statusDotClass(opt.value)}"></span>
              {opt.label}
            </span>
          </label>
        {/each}
        {#if selectedStatuses.size !== STATUS_OPTIONS.length}
          <div class="border-border mt-1 border-t pt-1">
            <Button
              variant="ghost"
              size="sm"
              class="w-full justify-center"
              onclick={() => (selectedStatuses = allStatuses())}
            >
              Reset
            </Button>
          </div>
        {/if}
      </Popover.Content>
    </Popover.Root>

    <div class="relative">
      <SearchIcon class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
      <Input
        type="text"
        placeholder="Workflow ID"
        bind:value={filters.workflow_id}
        class="w-52 pl-8"
      />
    </div>
    <div class="relative">
      <TextIcon class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
      <Input
        type="text"
        placeholder="Name (wildcard)"
        bind:value={filters.name}
        class="w-52 pl-8"
      />
    </div>

    <DateRangePicker bind:value={dateRange} placeholder="Started" />

    {#if hasActiveFilters}
      <Button variant="ghost" onclick={clearFilters}>Clear filters</Button>
    {/if}

    <div class="ml-auto flex items-center gap-3">
      <ToggleGroup.Root
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
            <Button variant="outline" {...props}>
              <ColumnsIcon />
              Columns
            </Button>
          {/snippet}
        </Popover.Trigger>
        <Popover.Content align="end" class="w-48 p-1">
          {#each Object.keys(COLUMN_LABELS) as key (key)}
            <label class="hover:bg-muted flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm">
              <Checkbox bind:checked={columns[key as ColumnKey]} />
              {COLUMN_LABELS[key as ColumnKey]}
            </label>
          {/each}
        </Popover.Content>
      </Popover.Root>
    </div>
  </div>

  {#if error}
    <div class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm">
      {error}
    </div>
  {:else if workflows === null}
    <p class="text-muted-foreground text-sm">Loading…</p>
  {:else if workflows.length === 0}
    <p class="text-muted-foreground text-sm">
      {hasActiveFilters
        ? "No workflows match the current filters."
        : "No workflows yet. Run a DBOS app pointed at this database to see data here."}
    </p>
  {:else}
    <div class="border-border bg-card overflow-hidden rounded-lg border shadow-xs">
      <table class="w-full text-left text-sm">
        <thead class="bg-muted/50 text-muted-foreground text-xs tracking-wide uppercase">
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
              class="hover:bg-muted/50 {grouped && w.depth === 0
                ? 'border-border border-t'
                : !grouped
                  ? 'border-border border-t'
                  : ''}"
            >
              {#if columns.status}
                <td class="px-4 {!grouped || w.depth === 0 ? 'py-2' : 'py-1'}">
                  <span
                    class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset {statusBadgeClass(
                      w.status,
                    )}"
                  >
                    {w.status ?? "—"}
                  </span>
                </td>
              {/if}
              {#if columns.workflow_id}
                <td
                  class="text-muted-foreground px-4 font-mono text-xs {!grouped || w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.workflow_id}
                >
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    class="hover:text-foreground hover:underline"
                  >
                    {w.workflow_id}
                  </a>
                </td>
              {/if}
              {#if columns.name}
                <td class="px-4 py-0 font-mono">
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
                </td>
              {/if}
              {#if columns.started}
                <td
                  class="text-muted-foreground px-4 {!grouped || w.depth === 0
                    ? 'py-2'
                    : 'py-1'}"
                  title={w.started_at}
                >
                  {formatRelative(w.started_at)}
                </td>
              {/if}
              {#if columns.updated}
                <td
                  class="text-muted-foreground px-4 {!grouped || w.depth === 0
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
