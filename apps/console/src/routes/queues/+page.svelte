<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type Queue = {
    queue_id: string;
    name: string;
    concurrency: number | null;
    worker_concurrency: number | null;
    rate_limit_max: number | null;
    rate_limit_period_sec: number | null;
    priority_enabled: boolean;
    partition_queue: boolean;
    polling_interval_sec: number;
    created_at_epoch_ms: number;
    updated_at_epoch_ms: number;
    enqueued: number;
    running: number;
  };

  let queues = $state<Queue[] | null>(null);
  let error = $state<string | null>(null);
  let handle: SubscriptionHandle | null = null;

  $effect(() => {
    breadcrumb.items = [{ label: "Queues", icon: "queues" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  onMount(() => {
    handle = realtimeClient.subscribe("queues", undefined, {
      onSnapshot: (data) => {
        if (Array.isArray(data)) {
          queues = data as Queue[];
          error = null;
        }
      },
      onUpdate: (data) => {
        if (Array.isArray(data)) {
          queues = data as Queue[];
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

  function formatRateLimit(max: number | null, period: number | null): string {
    if (max == null || period == null) return "—";
    return `${max} / ${formatPeriod(period)}`;
  }

  function formatPeriod(seconds: number): string {
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(seconds % 60 === 0 ? 0 : 1)}m`;
    return `${(seconds / 3600).toFixed(seconds % 3600 === 0 ? 0 : 1)}h`;
  }

  function formatNullableInt(v: number | null): string {
    return v == null ? "—" : String(v);
  }

  function formatTimestamp(ms: number): string {
    if (!ms) return "—";
    return new Date(ms).toISOString().replace("T", " ").slice(0, 19) + "Z";
  }
</script>

<div class="flex flex-col gap-4 p-6">
  <header class="flex min-h-9 items-center justify-between">
    <p class="text-muted-foreground text-xs">
      Queues registered with DBOS, with their persisted concurrency and rate-limit configuration.
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
    <p class="text-muted-foreground text-sm">No queues registered.</p>
  {:else}
    <Card.Root class="gap-0 py-0 shadow-xs">
      <Table.Root>
        <Table.Header class="bg-muted/40">
          <Table.Row class="hover:bg-muted/40">
            <Table.Head class="px-4">Name</Table.Head>
            <Table.Head class="px-4 text-right">Enqueued</Table.Head>
            <Table.Head class="px-4 text-right">Running</Table.Head>
            <Table.Head class="px-4 text-right">Concurrency</Table.Head>
            <Table.Head class="px-4 text-right">Worker</Table.Head>
            <Table.Head class="px-4">Rate limit</Table.Head>
            <Table.Head class="px-4">Flags</Table.Head>
            <Table.Head class="px-4">Updated</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each queues as q (q.queue_id)}
            <Table.Row>
              <Table.Cell class="px-4 py-2 font-mono">
                <a
                  href="/workflows/?queue_name={encodeURIComponent(q.name)}"
                  class="hover:text-foreground hover:underline"
                >
                  {q.name}
                </a>
              </Table.Cell>
              <Table.Cell class="px-4 py-2 text-right font-mono text-xs tabular-nums">
                {#if q.enqueued > 0}
                  <a
                    href="/workflows/?queue_name={encodeURIComponent(q.name)}&status=ENQUEUED"
                    class="hover:text-foreground hover:underline"
                  >
                    {q.enqueued}
                  </a>
                {:else}
                  <span class="text-muted-foreground">0</span>
                {/if}
              </Table.Cell>
              <Table.Cell class="px-4 py-2 text-right font-mono text-xs tabular-nums">
                {#if q.running > 0}
                  <a
                    href="/workflows/?queue_name={encodeURIComponent(q.name)}&status=PENDING"
                    class="hover:text-foreground hover:underline"
                  >
                    {q.running}
                  </a>
                {:else}
                  <span class="text-muted-foreground">0</span>
                {/if}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 text-right font-mono text-xs">
                {formatNullableInt(q.concurrency)}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 text-right font-mono text-xs">
                {formatNullableInt(q.worker_concurrency)}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 font-mono text-xs">
                {formatRateLimit(q.rate_limit_max, q.rate_limit_period_sec)}
              </Table.Cell>
              <Table.Cell class="px-4 py-2">
                <div class="flex flex-wrap gap-1">
                  {#if q.priority_enabled}
                    <Badge class="bg-muted text-muted-foreground">priority</Badge>
                  {/if}
                  {#if q.partition_queue}
                    <Badge class="bg-muted text-muted-foreground">partitioned</Badge>
                  {/if}
                  {#if !q.priority_enabled && !q.partition_queue}
                    <span class="text-muted-foreground text-xs">—</span>
                  {/if}
                </div>
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2 font-mono text-xs">
                {formatTimestamp(q.updated_at_epoch_ms)}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card.Root>
  {/if}
</div>
