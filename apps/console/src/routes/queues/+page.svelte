<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { formatRelative } from "$lib/format";

  type QueueSummary = {
    name: string;
    pending: number;
    enqueued: number;
    success: number;
    error: number;
    cancelled: number;
    total: number;
    last_activity: string | null;
  };

  let queues = $state<QueueSummary[] | null>(null);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  $effect(() => {
    breadcrumb.items = [
      { label: "Home", href: "/", icon: "home" },
      { label: "Queues" },
    ];
    return () => {
      breadcrumb.items = [];
    };
  });

  async function refresh() {
    try {
      const res = await fetch("/api/queues");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      queues = (await res.json()) as QueueSummary[];
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      queues = null;
    }
  }

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<div class="flex flex-col gap-4 p-6">
  <header class="flex items-baseline justify-between">
    <h1 class="text-lg font-semibold">Queues</h1>
    <p class="text-muted-foreground text-xs">
      Derived from <code class="font-mono">workflow_status.queue_name</code> — DBOS doesn't persist
      queue configuration.
    </p>
  </header>

  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {:else if queues === null}
    <p class="text-muted-foreground text-sm">Loading…</p>
  {:else if queues.length === 0}
    <p class="text-muted-foreground text-sm">
      No queues observed yet. DBOS only records a queue name once a workflow has been enqueued on
      it.
    </p>
  {:else}
    <div class="border-border bg-card overflow-hidden rounded-lg border shadow-xs">
      <table class="w-full text-left text-sm">
        <thead class="bg-muted/50 text-muted-foreground text-xs tracking-wide uppercase">
          <tr>
            <th class="px-4 py-2 font-medium">Queue</th>
            <th class="px-4 py-2 font-medium tabular-nums">Enqueued</th>
            <th class="px-4 py-2 font-medium tabular-nums">Pending</th>
            <th class="px-4 py-2 font-medium tabular-nums">Success</th>
            <th class="px-4 py-2 font-medium tabular-nums">Error</th>
            <th class="px-4 py-2 font-medium tabular-nums">Cancelled</th>
            <th class="px-4 py-2 font-medium tabular-nums">Total</th>
            <th class="px-4 py-2 font-medium">Last activity</th>
          </tr>
        </thead>
        <tbody>
          {#each queues as q (q.name)}
            <tr class="hover:bg-muted/50 border-border border-t">
              <td class="px-4 py-2 font-mono">
                <a
                  href="/workflows/?queue_name={encodeURIComponent(q.name)}"
                  class="hover:text-foreground hover:underline"
                >
                  {q.name}
                </a>
              </td>
              <td class="px-4 py-2 tabular-nums">{q.enqueued}</td>
              <td class="px-4 py-2 tabular-nums">{q.pending}</td>
              <td class="text-muted-foreground px-4 py-2 tabular-nums">{q.success}</td>
              <td class="px-4 py-2 tabular-nums {q.error > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}">
                {q.error}
              </td>
              <td class="text-muted-foreground px-4 py-2 tabular-nums">{q.cancelled}</td>
              <td class="px-4 py-2 tabular-nums">{q.total}</td>
              <td
                class="text-muted-foreground px-4 py-2"
                title={q.last_activity ?? ""}
              >
                {formatRelative(q.last_activity)}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
