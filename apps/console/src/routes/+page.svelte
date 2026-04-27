<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import ActivityIcon from "@lucide/svelte/icons/activity";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import AlertTriangleIcon from "@lucide/svelte/icons/triangle-alert";
  import ListIcon from "@lucide/svelte/icons/list";
  import BellIcon from "@lucide/svelte/icons/bell";
  import CalendarClockIcon from "@lucide/svelte/icons/calendar-clock";
  import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { statusBadgeClass, type Workflow } from "$lib/workflow-tree";
  import { formatRelative } from "$lib/format";

  type Stats = {
    total: number;
    in_flight: number;
    failed_recent: number;
    active_queues: number;
    pending_notifications: number;
    active_schedules: number;
  };

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

  let stats = $state<Stats | null>(null);
  let recents = $state<Workflow[] | null>(null);
  let queues = $state<QueueSummary[] | null>(null);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  $effect(() => {
    breadcrumb.items = [{ label: "Home", icon: "home" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  async function refresh() {
    try {
      const [s, w, q] = await Promise.all([
        fetch("/api/stats").then((r) => {
          if (!r.ok) throw new Error(`stats HTTP ${r.status}`);
          return r.json() as Promise<Stats>;
        }),
        fetch("/api/workflows?limit=8&grouped=false").then((r) => {
          if (!r.ok) throw new Error(`workflows HTTP ${r.status}`);
          return r.json() as Promise<Workflow[]>;
        }),
        fetch("/api/queues").then((r) => {
          if (!r.ok) throw new Error(`queues HTTP ${r.status}`);
          return r.json() as Promise<QueueSummary[]>;
        }),
      ]);
      stats = s;
      recents = w;
      queues = q;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  type Tile = {
    label: string;
    value: number | undefined;
    href: string;
    icon: typeof ActivityIcon;
    accent: string;
    sub?: string;
  };

  const tiles = $derived<Tile[]>([
    {
      label: "Active queues",
      value: stats?.active_queues,
      href: "/queues/",
      icon: LayersIcon,
      accent: "text-foreground",
      sub: "With workflows in flight",
    },
    {
      label: "Pending notifications",
      value: stats?.pending_notifications,
      href: "/notifications/",
      icon: BellIcon,
      accent: "text-foreground",
      sub: "Unconsumed messages",
    },
    {
      label: "Active schedules",
      value: stats?.active_schedules,
      href: "/schedules/",
      icon: CalendarClockIcon,
      accent: "text-foreground",
      sub: "Cron workflows",
    },
  ]);

  const inFlightHref = "/workflows/?status=PENDING&status=ENQUEUED&status=DELAYED";
  const failedHref = "/workflows/?status=ERROR&status=MAX_RECOVERY_ATTEMPTS_EXCEEDED";

  const activeQueues = $derived(
    (queues ?? []).filter((q) => q.pending > 0 || q.enqueued > 0).slice(0, 6),
  );
</script>

<div class="flex flex-col gap-6 p-6">
  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {/if}

  <section class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
    <div
      class="border-border bg-card group flex flex-col gap-2 rounded-lg border p-4 shadow-xs"
    >
      <div class="flex items-center justify-between">
        <a
          href="/workflows/"
          class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide transition-colors"
        >
          Workflows
        </a>
        <ListIcon class="text-muted-foreground h-4 w-4" />
      </div>
      <a
        href="/workflows/"
        class="hover:text-muted-foreground text-2xl font-semibold tabular-nums transition-colors"
      >
        {stats?.total ?? "—"}
      </a>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <a
          href={inFlightHref}
          class="hover:text-foreground inline-flex items-center gap-1.5 text-blue-600 transition-colors dark:text-blue-400"
        >
          <ActivityIcon class="h-3 w-3" />
          <span class="font-semibold tabular-nums">{stats?.in_flight ?? "—"}</span>
          <span class="text-muted-foreground">in flight</span>
        </a>
        <a
          href={failedHref}
          class="hover:text-foreground inline-flex items-center gap-1.5 text-red-600 transition-colors dark:text-red-400"
        >
          <AlertTriangleIcon class="h-3 w-3" />
          <span class="font-semibold tabular-nums">{stats?.failed_recent ?? "—"}</span>
          <span class="text-muted-foreground">failed (24h)</span>
        </a>
      </div>
    </div>

    {#each tiles as tile (tile.label)}
      <a
        href={tile.href}
        class="border-border bg-card hover:border-muted-foreground/40 hover:bg-muted/30 flex flex-col gap-2 rounded-lg border p-4 shadow-xs transition-colors"
      >
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground text-xs font-medium uppercase tracking-wide">
            {tile.label}
          </span>
          <tile.icon class="text-muted-foreground h-4 w-4 {tile.accent}" />
        </div>
        <div class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold tabular-nums {tile.accent}">
            {tile.value ?? "—"}
          </span>
        </div>
        {#if tile.sub}
          <span class="text-muted-foreground text-xs">{tile.sub}</span>
        {/if}
      </a>
    {/each}
  </section>

  <section class="grid grid-cols-1 gap-6 lg:grid-cols-3">
    <div class="border-border bg-card flex flex-col rounded-lg border shadow-xs lg:col-span-2">
      <header class="border-border flex items-center justify-between border-b px-4 py-3">
        <h2 class="text-sm font-semibold">Recent workflows</h2>
        <a
          href="/workflows/"
          class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          View all
          <ArrowRightIcon class="h-3 w-3" />
        </a>
      </header>
      {#if recents === null}
        <p class="text-muted-foreground p-4 text-sm">Loading…</p>
      {:else if recents.length === 0}
        <p class="text-muted-foreground p-4 text-sm">
          No workflows yet. Run a DBOS app pointed at this database to see data here.
        </p>
      {:else}
        <table class="w-full text-left text-sm">
          <thead class="bg-muted/30 text-muted-foreground text-xs tracking-wide uppercase">
            <tr>
              <th class="px-4 py-2 font-medium">Status</th>
              <th class="px-4 py-2 font-medium">Name</th>
              <th class="px-4 py-2 font-medium">Workflow ID</th>
              <th class="px-4 py-2 font-medium">Started</th>
            </tr>
          </thead>
          <tbody>
            {#each recents as w (w.workflow_id)}
              <tr class="hover:bg-muted/40 border-border border-t">
                <td class="px-4 py-2">
                  <span
                    class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset {statusBadgeClass(
                      w.status,
                    )}"
                  >
                    {w.status ?? "—"}
                  </span>
                </td>
                <td class="px-4 py-2 font-mono">
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    class="hover:text-foreground hover:underline"
                  >
                    {w.name ?? "—"}
                  </a>
                </td>
                <td
                  class="text-muted-foreground px-4 py-2 font-mono text-xs"
                  title={w.workflow_id}
                >
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    class="hover:text-foreground hover:underline"
                  >
                    {w.workflow_id}
                  </a>
                </td>
                <td class="text-muted-foreground px-4 py-2" title={w.started_at}>
                  {formatRelative(w.started_at)}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <div class="border-border bg-card flex flex-col rounded-lg border shadow-xs">
      <header class="border-border flex items-center justify-between border-b px-4 py-3">
        <h2 class="text-sm font-semibold">Active queues</h2>
        <a
          href="/queues/"
          class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          View all
          <ArrowRightIcon class="h-3 w-3" />
        </a>
      </header>
      {#if queues === null}
        <p class="text-muted-foreground p-4 text-sm">Loading…</p>
      {:else if activeQueues.length === 0}
        <p class="text-muted-foreground p-4 text-sm">
          No queues with workflows in flight.
        </p>
      {:else}
        <ul class="divide-border divide-y">
          {#each activeQueues as q (q.name)}
            <li>
              <a
                href="/workflows/?queue_name={encodeURIComponent(q.name)}"
                class="hover:bg-muted/40 flex items-center justify-between px-4 py-2.5 transition-colors"
              >
                <span class="truncate font-mono text-sm" title={q.name}>{q.name}</span>
                <span class="text-muted-foreground flex items-center gap-3 text-xs tabular-nums">
                  {#if q.enqueued > 0}
                    <span title="Enqueued">
                      <span
                        class="inline-block h-1.5 w-1.5 -translate-y-px rounded-full bg-blue-500"
                        aria-hidden="true"
                      ></span>
                      {q.enqueued}
                    </span>
                  {/if}
                  {#if q.pending > 0}
                    <span title="Pending">
                      <span
                        class="inline-block h-1.5 w-1.5 -translate-y-px rounded-full bg-blue-400"
                        aria-hidden="true"
                      ></span>
                      {q.pending}
                    </span>
                  {/if}
                </span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </section>
</div>
