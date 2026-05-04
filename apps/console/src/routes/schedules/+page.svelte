<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatStatus } from "$lib/workflow-tree";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type WorkflowSchedule = {
    schedule_id: string;
    schedule_name: string;
    workflow_name: string;
    workflow_class_name: string | null;
    schedule: string;
    status: string;
    last_fired_at: string | null;
    automatic_backfill: boolean;
    cron_timezone: string | null;
    queue_name: string | null;
  };

  let schedules = $state<WorkflowSchedule[] | null>(null);
  let error = $state<string | null>(null);
  let handle: SubscriptionHandle | null = null;

  $effect(() => {
    breadcrumb.items = [{ label: "Schedules", icon: "schedules" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  onMount(() => {
    handle = realtimeClient.subscribe("schedules", undefined, {
      onSnapshot: (data) => {
        if (Array.isArray(data)) {
          schedules = data as WorkflowSchedule[];
          error = null;
        }
      },
      onUpdate: (data) => {
        if (Array.isArray(data)) {
          schedules = data as WorkflowSchedule[];
        }
      },
      onError: (_code, message) => {
        error = message;
      },
    });
  });

  onDestroy(() => {
    handle?.dispose();
  });

  function statusClass(status: string): string {
    if (status === "ACTIVE") return "bg-status-success/15 text-status-success";
    return "bg-muted text-muted-foreground";
  }
</script>

<div class="flex flex-col gap-4 p-6">
  <header class="flex min-h-9 items-center justify-between">
    <p class="text-muted-foreground text-xs">
      Cron-style scheduled workflows registered with DBOS.
    </p>
  </header>

  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {:else if schedules === null}
    <p class="text-muted-foreground text-sm">Loading…</p>
  {:else if schedules.length === 0}
    <p class="text-muted-foreground text-sm">
      No scheduled workflows registered.
    </p>
  {:else}
    <Card.Root class="gap-0 py-0 shadow-xs">
      <Table.Root>
        <Table.Header class="bg-muted/40">
          <Table.Row class="hover:bg-muted/40">
            <Table.Head class="px-4">Status</Table.Head>
            <Table.Head class="px-4">Name</Table.Head>
            <Table.Head class="px-4">Workflow</Table.Head>
            <Table.Head class="px-4">Schedule</Table.Head>
            <Table.Head class="px-4">Timezone</Table.Head>
            <Table.Head class="px-4">Queue</Table.Head>
            <Table.Head class="px-4">Last fired</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each schedules as s (s.schedule_id)}
            <Table.Row>
              <Table.Cell class="px-4 py-2">
                <Badge class={statusClass(s.status)}>{formatStatus(s.status)}</Badge>
              </Table.Cell>
              <Table.Cell class="px-4 py-2 font-mono">{s.schedule_name}</Table.Cell>
              <Table.Cell
                class="px-4 py-2 font-mono text-xs"
                title={s.workflow_class_name ?? ""}
              >
                {#if s.workflow_class_name}
                  <span class="text-muted-foreground">{s.workflow_class_name}.</span>
                {/if}{s.workflow_name}
              </Table.Cell>
              <Table.Cell class="px-4 py-2 font-mono text-xs">{s.schedule}</Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 text-xs">
                {s.cron_timezone ?? "UTC"}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 font-mono text-xs">
                {#if s.queue_name}
                  <a
                    href="/workflows/?queue_name={encodeURIComponent(s.queue_name)}"
                    class="hover:text-foreground hover:underline"
                  >
                    {s.queue_name}
                  </a>
                {:else}
                  —
                {/if}
              </Table.Cell>
              <Table.Cell
                class="text-muted-foreground px-4 py-2 text-xs"
                title={s.last_fired_at ?? ""}
              >
                {s.last_fired_at ?? "—"}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card.Root>
  {/if}
</div>
