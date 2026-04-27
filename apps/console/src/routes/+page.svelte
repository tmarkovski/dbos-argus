<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import ActivityIcon from "@lucide/svelte/icons/activity";
  import AlertTriangleIcon from "@lucide/svelte/icons/triangle-alert";
  import BellIcon from "@lucide/svelte/icons/bell";
  import CalendarClockIcon from "@lucide/svelte/icons/calendar-clock";
  import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
  import TrendingUpIcon from "@lucide/svelte/icons/trending-up";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { statusBadgeClass, type Workflow } from "$lib/workflow-tree";
  import { formatRelative } from "$lib/format";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";

  type Stats = {
    total: number;
    in_flight: number;
    failed_recent: number;
    pending_notifications: number;
    active_schedules: number;
  };

  let stats = $state<Stats | null>(null);
  let recents = $state<Workflow[] | null>(null);
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
      const [s, w] = await Promise.all([
        fetch("/api/stats").then((r) => {
          if (!r.ok) throw new Error(`stats HTTP ${r.status}`);
          return r.json() as Promise<Stats>;
        }),
        fetch("/api/workflows?limit=8&grouped=false").then((r) => {
          if (!r.ok) throw new Error(`workflows HTTP ${r.status}`);
          return r.json() as Promise<Workflow[]>;
        }),
      ]);
      stats = s;
      recents = w;
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

  const inFlightHref = "/workflows/?status=PENDING&status=ENQUEUED&status=DELAYED";
  const failedHref = "/workflows/?status=ERROR&status=MAX_RECOVERY_ATTEMPTS_EXCEEDED";
</script>

<div class="@container/main flex flex-col gap-4 p-4 md:gap-6 md:p-6">
  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {/if}

  <div
    class="*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4"
  >
    <Card.Root>
      <Card.Header>
        <Card.Description>Total workflows</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <a href="/workflows/" class="hover:text-muted-foreground transition-colors">
            {stats?.total ?? "—"}
          </a>
        </Card.Title>
        <Card.Action>
          <a href={inFlightHref} class="hover:opacity-80">
            <Badge variant="outline" class="gap-1">
              <ActivityIcon class="size-3" />
              {stats?.in_flight ?? "—"} in flight
            </Badge>
          </a>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="flex-col items-start gap-1.5 text-sm">
        <a
          href={failedHref}
          class="line-clamp-1 flex items-center gap-1.5 font-medium hover:underline"
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
      <Card.Header>
        <Card.Description>In flight</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <a href={inFlightHref} class="hover:text-muted-foreground transition-colors">
            {stats?.in_flight ?? "—"}
          </a>
        </Card.Title>
        <Card.Action>
          <Badge variant="outline" class="gap-1">
            <ActivityIcon class="size-3" />
            Live
          </Badge>
        </Card.Action>
      </Card.Header>
      <Card.Footer class="flex-col items-start gap-1.5 text-sm">
        <div class="line-clamp-1 flex items-center gap-1.5 font-medium">
          Pending, enqueued and delayed
          <TrendingUpIcon class="size-4" />
        </div>
        <div class="text-muted-foreground">
          Workflows currently executing or waiting
        </div>
      </Card.Footer>
    </Card.Root>

    <Card.Root>
      <Card.Header>
        <Card.Description>Pending notifications</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <a
            href="/notifications/"
            class="hover:text-muted-foreground transition-colors"
          >
            {stats?.pending_notifications ?? "—"}
          </a>
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
        <div class="text-muted-foreground">Awaiting recv() or getEvent()</div>
      </Card.Footer>
    </Card.Root>

    <Card.Root>
      <Card.Header>
        <Card.Description>Active schedules</Card.Description>
        <Card.Title
          class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
        >
          <a href="/schedules/" class="hover:text-muted-foreground transition-colors">
            {stats?.active_schedules ?? "—"}
          </a>
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
  </div>

  <Card.Root class="gap-0 py-0 shadow-xs">
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
            <Table.Head>Workflow ID</Table.Head>
            <Table.Head class="px-4">Started</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each recents as w (w.workflow_id)}
            <Table.Row>
              <Table.Cell class="px-4">
                <Badge class={statusBadgeClass(w.status)}>{w.status ?? "—"}</Badge>
              </Table.Cell>
              <Table.Cell class="font-mono">
                <a
                  href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                  class="hover:text-foreground hover:underline"
                >
                  {w.name ?? "—"}
                </a>
              </Table.Cell>
              <Table.Cell
                class="text-muted-foreground font-mono text-xs"
                title={w.workflow_id}
              >
                <a
                  href="/workflows/{encodeURIComponent(w.workflow_id)}/"
                  class="hover:text-foreground hover:underline"
                >
                  {w.workflow_id}
                </a>
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4" title={w.started_at}>
                {formatRelative(w.started_at)}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    {/if}
  </Card.Root>
</div>
