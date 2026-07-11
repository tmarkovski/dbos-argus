<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { slide } from "svelte/transition";
  import ActivityIcon from "@lucide/svelte/icons/activity";
  import AlertTriangleIcon from "@lucide/svelte/icons/triangle-alert";
  import BellIcon from "@lucide/svelte/icons/bell";
  import CalendarClockIcon from "@lucide/svelte/icons/calendar-clock";
  import DatabaseIcon from "@lucide/svelte/icons/database";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import ListTodoIcon from "@lucide/svelte/icons/list-todo";
  import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { formatStatus, statusBadgeClass, type Workflow } from "$lib/workflow-tree";
  import { formatRelative } from "$lib/format";
  import {
    diagnosticsIssueSummary,
    getConnectionIndicatorState,
  } from "$lib/connection-diagnostics";
  import { connectionState } from "$lib/connection-state.svelte";
  import { statsState } from "$lib/stats.svelte";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import WorkflowThroughputChart from "$lib/components/WorkflowThroughputChart.svelte";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type QueueSummary = {
    queue_id: string;
    name: string;
    enqueued: number;
    running: number;
  };

  let recents = $state<Workflow[] | null>(null);
  let queues = $state<QueueSummary[] | null>(null);
  let error = $state<string | null>(null);
  let recentsHandle: SubscriptionHandle | null = null;
  let queuesHandle: SubscriptionHandle | null = null;

  const stats = $derived(statsState.data);

  const topQueues = $derived.by(() => {
    if (!queues) return [] as QueueSummary[];
    return [...queues]
      .sort((a, b) => b.enqueued + b.running - (a.enqueued + a.running))
      .slice(0, 3);
  });

  $effect(() => {
    breadcrumb.items = [{ label: "Dashboard", icon: "home" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  function applyRecents(data: unknown): void {
    if (!Array.isArray(data)) return;
    recents = data as Workflow[];
    // Only clear the local error; the layout-level statsState may still
    // have its own error which we surface below.
    error = statsState.error;
  }

  function applyQueues(data: unknown): void {
    if (!Array.isArray(data)) return;
    queues = data as QueueSummary[];
  }

  onMount(() => {
    recentsHandle = realtimeClient.subscribe(
      "workflows",
      { limit: 8, grouped: false },
      {
        onSnapshot: applyRecents,
        onUpdate: applyRecents,
        onError: (_code, message) => {
          error = message;
        },
      },
    );
    queuesHandle = realtimeClient.subscribe("queues", undefined, {
      onSnapshot: applyQueues,
      onUpdate: applyQueues,
    });
  });

  onDestroy(() => {
    recentsHandle?.dispose();
    queuesHandle?.dispose();
  });

  const inFlightHref = "/workflows/?status=PENDING&status=ENQUEUED&status=DELAYED";
  const enqueuedHref = "/workflows/?status=ENQUEUED";
  const failedHref = "/workflows/?status=ERROR&status=MAX_RECOVERY_ATTEMPTS_EXCEEDED";

  const connectionIndicatorState = $derived(
    getConnectionIndicatorState({
      fetchError: connectionState.fetchError,
      health: connectionState.health,
      diagnostics: connectionState.diagnostics,
    }),
  );

  // Hold the banner for two ticks of the 1s connectionState refresh — by
  // then the WS has had time to land its first health snapshot or to
  // surface a real fetchError, so we don't flash a red banner during the
  // normal handshake on a fresh page load.
  const ALERT_GRACE_MS = 2000;
  let alertReady = $state(false);

  $effect(() => {
    if (connectionIndicatorState === "connected") {
      alertReady = false;
      return;
    }
    const t = setTimeout(() => {
      alertReady = true;
    }, ALERT_GRACE_MS);
    return () => clearTimeout(t);
  });

  const connectionAlert = $derived.by(() => {
    if (!alertReady) return null;

    if (connectionIndicatorState === "disconnected") {
      const detail =
        connectionState.fetchError ?? connectionState.health?.database_error ?? null;
      return {
        tone: "error" as const,
        title: "Database disconnected",
        detail: detail ?? "Argus can't reach the DBOS database.",
      };
    }
    if (connectionIndicatorState === "issues") {
      return {
        tone: "warning" as const,
        title: "Schema mismatch",
        detail:
          diagnosticsIssueSummary(connectionState.diagnostics) ??
          "The DBOS schema doesn't match what Argus expects.",
      };
    }
    return null;
  });
</script>

<div class="@container/main flex flex-col gap-4 p-4 md:gap-5 md:p-5">
  {#if connectionAlert}
    <button
      type="button"
      onclick={() => connectionState.open()}
      transition:slide={{ duration: 220 }}
      class="flex w-full items-center gap-3 rounded-lg border p-4 text-left text-sm transition-colors {connectionAlert.tone ===
      'error'
        ? 'border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/15'
        : 'border-status-warning/40 bg-status-warning/10 text-status-warning hover:bg-status-warning/15'}"
    >
      {#if connectionAlert.tone === "error"}
        <DatabaseIcon class="size-5 flex-none" />
      {:else}
        <AlertTriangleIcon class="size-5 flex-none" />
      {/if}
      <div class="flex min-w-0 flex-1 flex-col gap-0.5">
        <span class="font-semibold">{connectionAlert.title}</span>
        <span class="truncate opacity-80" title={connectionAlert.detail}>
          {connectionAlert.detail}
        </span>
      </div>
      <span class="text-xs font-medium opacity-80 hover:underline">View details</span>
    </button>
  {/if}

  {#if error && connectionIndicatorState === "connected"}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {/if}

  <div
    class="*:data-[slot=card]:relative *:data-[slot=card]:cursor-pointer *:data-[slot=card]:transition-colors *:data-[slot=card]:hover:border-foreground/20 *:data-[slot=card]:hover:bg-muted/20 grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4"
  >
    <Card.Root>
      <a
        href="/workflows/"
        class="absolute inset-0 rounded-lg"
        aria-label="View all workflows"
      ></a>
      <Card.Header>
        <Card.Description>Total workflows</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <span class="hover:text-muted-foreground transition-colors">
            {stats?.total ?? "—"}
          </span>
        </Card.Title>
        <Card.Action class="flex flex-col items-end gap-1">
          <a href={inFlightHref} class="relative z-10 hover:opacity-80">
            <Badge variant="outline" class="gap-1">
              <ActivityIcon class="size-3" />
              {stats?.in_flight ?? "—"} in flight
            </Badge>
          </a>
          <a href={enqueuedHref} class="relative z-10 hover:opacity-80">
            <Badge variant="outline" class="gap-1">
              <ListTodoIcon class="size-3" />
              {stats?.enqueued ?? "—"} queued
            </Badge>
          </a>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="flex-col items-start gap-1.5 text-sm">
        <a
          href={failedHref}
          class="relative z-10 line-clamp-1 flex items-center gap-1.5 font-medium hover:underline"
        >
          {stats?.failed_recent ?? "—"} failed in the last 24h
          <AlertTriangleIcon class="size-4" />
        </a>
        <div class="text-muted-foreground">
          Across all DBOS workflows in this database
        </div>
      </Card.Footer>
    </Card.Root>

    <Card.Root>
      <a
        href="/notifications/"
        class="absolute inset-0 rounded-lg"
        aria-label="View notifications"
      ></a>
      <Card.Header>
        <Card.Description>Pending notifications</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <span class="hover:text-muted-foreground transition-colors">
            {stats?.pending_notifications ?? "—"}
          </span>
        </Card.Title>
        <Card.Action>
          <Badge variant="outline" class="gap-1">
            <BellIcon class="size-3" />
            Inbox
          </Badge>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="flex-col items-start gap-1.5 text-sm">
        <div class="line-clamp-1 font-medium">Unconsumed messages</div>
        <div class="text-muted-foreground">Sent via send(), awaiting recv()</div>
      </Card.Footer>
    </Card.Root>

    <Card.Root>
      <a
        href="/schedules/"
        class="absolute inset-0 rounded-lg"
        aria-label="View schedules"
      ></a>
      <Card.Header>
        <Card.Description>Active schedules</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <span class="hover:text-muted-foreground transition-colors">
            {stats?.active_schedules ?? "—"}
          </span>
        </Card.Title>
        <Card.Action>
          <Badge variant="outline" class="gap-1">
            <CalendarClockIcon class="size-3" />
            Cron
          </Badge>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="flex-col items-start gap-1.5 text-sm">
        <div class="line-clamp-1 font-medium">Auto-triggered workflows</div>
        <div class="text-muted-foreground">Registered with @DBOS.scheduled</div>
      </Card.Footer>
    </Card.Root>

    <Card.Root>
      <a
        href="/queues/"
        class="absolute inset-0 rounded-lg"
        aria-label="View queues"
      ></a>
      <Card.Header>
        <Card.Description>Top queues</Card.Description>
        <Card.Title class="text-sm font-medium">
          <span class="hover:text-muted-foreground transition-colors">
            By in-flight workload
          </span>
        </Card.Title>
        <Card.Action>
          <Badge variant="outline" class="gap-1 tabular-nums">
            <LayersIcon class="size-3" />
            {stats?.total_queues ?? "—"}
          </Badge>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="mt-auto flex-col items-stretch gap-1.5 text-sm">
        {#if queues === null}
          <div class="text-muted-foreground text-xs">Loading…</div>
        {:else if topQueues.length === 0}
          <div class="text-muted-foreground text-xs">No queues registered.</div>
        {:else}
          <div class="text-muted-foreground flex items-center gap-3 text-xs font-medium tracking-wide uppercase">
            <span class="min-w-0 flex-1"></span>
            <span class="text-status-queued/80 w-10 flex-none text-right">Queued</span>
            <span class="text-status-running/80 w-10 flex-none text-right">Running</span>
          </div>
          {#each topQueues as q (q.queue_id)}
            <a
              href="/workflows/?queue_name={encodeURIComponent(
                q.name,
              )}&status=ENQUEUED&status=PENDING"
              class="group relative z-10 flex items-center gap-3 text-xs"
            >
              <span
                class="text-muted-foreground group-hover:text-foreground min-w-0 flex-1 truncate font-mono"
              >
                {q.name}
              </span>
              <span
                class="text-status-queued w-10 flex-none text-right font-mono font-semibold tabular-nums"
              >
                {q.enqueued}
              </span>
              <span
                class="text-status-running w-10 flex-none text-right font-mono font-semibold tabular-nums"
              >
                {q.running}
              </span>
            </a>
          {/each}
        {/if}
      </Card.Footer>
    </Card.Root>
  </div>

  <div class="grid grid-cols-1 items-start gap-4 @5xl/main:grid-cols-2 md:gap-5">
    <WorkflowThroughputChart />

    <Card.Root class="gap-0 overflow-hidden py-0">
      <Card.Header class="border-b py-4">
        <Card.Title class="text-base font-semibold">Recent workflows</Card.Title>
        <Card.Description>The most recent workflow runs from this database.</Card.Description>
        <Card.Action>
          <a
            href="/workflows/"
            class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
          >
            View all
            <ArrowRightIcon class="size-3" />
          </a>
        </Card.Action>
      </Card.Header>

      {#if recents === null}
        <p class="text-muted-foreground p-6 text-sm">Loading…</p>
      {:else if recents.length === 0}
        <p class="text-muted-foreground p-6 text-sm">
          No workflows yet. Run a DBOS app pointed at this database to see data here.
        </p>
      {:else}
        <Table.Root>
          <Table.Header class="bg-muted/40">
            <Table.Row class="hover:bg-muted/40">
              <Table.Head class="px-4">Status</Table.Head>
              <Table.Head>Name</Table.Head>
              <Table.Head class="px-4">Started</Table.Head>
              <Table.Head>Workflow ID</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each recents as w (w.workflow_id)}
              <Table.Row>
                <Table.Cell class="px-4">
                  <Badge class={statusBadgeClass(w.status)}>{formatStatus(w.status)}</Badge>
                </Table.Cell>
                <Table.Cell class="font-mono">
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    class="hover:text-foreground hover:underline"
                  >
                    {w.name ?? "—"}
                  </a>
                </Table.Cell>
                <Table.Cell class="text-muted-foreground px-4" title={w.started_at}>
                  {formatRelative(w.started_at)}
                </Table.Cell>
                <Table.Cell
                  class="text-muted-foreground w-full max-w-0 font-mono text-xs"
                  title={w.workflow_id}
                >
                  <a
                    href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                    class="hover:text-foreground block truncate hover:underline"
                  >
                    {w.workflow_id}
                  </a>
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      {/if}
    </Card.Root>
  </div>
</div>
