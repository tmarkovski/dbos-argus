<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatRelative } from "$lib/format";

  type Notification = {
    message_uuid: string;
    destination_uuid: string;
    topic: string | null;
    consumed: boolean;
    created_at: string;
  };

  type View = "pending" | "all";

  let view = $state<View>("pending");
  let items = $state<Notification[] | null>(null);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  $effect(() => {
    breadcrumb.items = [{ label: "Notifications", icon: "notifications" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  async function refresh() {
    try {
      const url =
        view === "pending"
          ? "/api/notifications?consumed=false"
          : "/api/notifications";
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      items = (await res.json()) as Notification[];
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      items = null;
    }
  }

  $effect(() => {
    view;
    refresh();
  });

  onMount(() => {
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<div class="flex flex-col gap-4 p-6">
  <header class="flex flex-wrap items-baseline justify-between gap-3">
    <h1 class="text-lg font-semibold">Notifications</h1>
    <div class="flex items-center gap-3">
      <p class="text-muted-foreground text-xs">
        Messages from <code class="font-mono">DBOS.send</code>; pending ones are waiting on a
        <code class="font-mono">DBOS.recv</code>.
      </p>
      <ToggleGroup.Root
        type="single"
        variant="outline"
        value={view}
        onValueChange={(v) => {
          if (v) view = v as View;
        }}
      >
        <ToggleGroup.Item value="pending">Pending</ToggleGroup.Item>
        <ToggleGroup.Item value="all">All</ToggleGroup.Item>
      </ToggleGroup.Root>
    </div>
  </header>

  {#if error}
    <div
      class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border p-3 text-sm"
    >
      {error}
    </div>
  {:else if items === null}
    <p class="text-muted-foreground text-sm">Loading…</p>
  {:else if items.length === 0}
    <p class="text-muted-foreground text-sm">
      {view === "pending"
        ? "No pending notifications. Every message has been received."
        : "No notifications recorded."}
    </p>
  {:else}
    <Card.Root class="gap-0 py-0 shadow-xs">
      <Table.Root>
        <Table.Header class="bg-muted/40">
          <Table.Row class="hover:bg-muted/40">
            <Table.Head class="px-4">State</Table.Head>
            <Table.Head class="px-4">Destination workflow</Table.Head>
            <Table.Head class="px-4">Topic</Table.Head>
            <Table.Head class="px-4">Sent</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each items as n (n.message_uuid)}
            <Table.Row>
              <Table.Cell class="px-4 py-2">
                {#if n.consumed}
                  <Badge variant="secondary">Consumed</Badge>
                {:else}
                  <Badge
                    class="bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-400"
                  >
                    Pending
                  </Badge>
                {/if}
              </Table.Cell>
              <Table.Cell
                class="text-muted-foreground px-4 py-2 font-mono text-xs"
                title={n.destination_uuid}
              >
                <a
                  href="/workflows/{encodeURIComponent(n.destination_uuid)}/"
                  class="hover:text-foreground hover:underline"
                >
                  {n.destination_uuid}
                </a>
              </Table.Cell>
              <Table.Cell class="px-4 py-2 font-mono text-xs">
                {n.topic ?? "—"}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2" title={n.created_at}>
                {formatRelative(n.created_at)}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card.Root>
  {/if}
</div>
