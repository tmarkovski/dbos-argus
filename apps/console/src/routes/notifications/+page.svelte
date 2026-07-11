<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatRelative } from "$lib/format";
  import { statusDotClass } from "$lib/workflow-tree";
  import { Button } from "$lib/components/ui/button/index.js";
  import Copy from "@lucide/svelte/icons/copy";
  import Check from "@lucide/svelte/icons/check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Eye from "@lucide/svelte/icons/eye";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type WorkflowAncestor = {
    workflow_id: string;
    name: string | null;
    status: string | null;
  };

  type Notification = {
    message_uuid: string;
    destination_uuid: string;
    topic: string | null;
    consumed: boolean;
    created_at: string;
    message: string | null;
    serialization: string | null;
    message_decoded: string | null;
    destination_ancestors: WorkflowAncestor[];
  };

  type View = "pending" | "all";
  type ViewMode = "raw" | "decoded";

  let view = $state<View>("pending");
  let items = $state<Notification[] | null>(null);
  let error = $state<string | null>(null);
  let handle: SubscriptionHandle | null = null;
  let selected = $state<Notification | null>(null);
  let preferredMode = $state<ViewMode>("decoded");

  $effect(() => {
    breadcrumb.items = [{ label: "Notifications", icon: "notifications" }];
    return () => {
      breadcrumb.items = [];
    };
  });

  function buildParams(): Record<string, unknown> {
    return view === "pending" ? { consumed: false } : {};
  }

  function applySnapshot(data: unknown): void {
    if (!Array.isArray(data)) return;
    const next = data as Notification[];
    items = next;
    // Keep the selected sheet's content fresh if the row is still in the list.
    if (selected) {
      const updated = next.find((n) => n.message_uuid === selected!.message_uuid);
      selected = updated ?? selected;
    }
    error = null;
  }

  // View-toggle changes route through update_params so the same poller is
  // re-keyed on the server instead of torn down.
  $effect(() => {
    view;
    handle?.updateParams(buildParams());
  });

  onMount(() => {
    handle = realtimeClient.subscribe("notifications", buildParams(), {
      onSnapshot: applySnapshot,
      onUpdate: applySnapshot,
      onError: (_code, message) => {
        error = message;
      },
    });
  });

  onDestroy(() => {
    handle?.dispose();
    if (copyTimer) clearTimeout(copyTimer);
  });

  const messagePayload = $derived.by<{
    raw: string | null;
    decoded: string | null;
  }>(() => {
    if (!selected) return { raw: null, decoded: null };
    return { raw: selected.message, decoded: selected.message_decoded };
  });

  const effectiveMode = $derived.by<ViewMode>(() => {
    if (preferredMode === "decoded" && messagePayload.decoded !== null) return "decoded";
    return "raw";
  });

  const displayedMessage = $derived(
    effectiveMode === "decoded" && messagePayload.decoded !== null
      ? messagePayload.decoded
      : (messagePayload.raw ?? ""),
  );

  let justCopied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | null = null;

  async function copyMessage() {
    if (!displayedMessage) return;
    try {
      await navigator.clipboard.writeText(displayedMessage);
      justCopied = true;
      if (copyTimer) clearTimeout(copyTimer);
      copyTimer = setTimeout(() => (justCopied = false), 1500);
    } catch (e) {
      console.warn("clipboard write failed", e);
    }
  }
</script>

<div class="flex flex-col gap-4 p-4 md:p-5">
  <header class="flex min-h-9 flex-wrap items-center justify-between gap-3">
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
    <Card.Root class="gap-0 py-0">
      <Table.Root>
        <Table.Header class="bg-muted/40">
          <Table.Row class="hover:bg-muted/40">
            <Table.Head class="w-32 px-4">Message ID</Table.Head>
            <Table.Head class="px-4">Destination workflow</Table.Head>
            <Table.Head class="px-4">Topic</Table.Head>
            <Table.Head class="px-4">State</Table.Head>
            <Table.Head class="px-4">Sent</Table.Head>
            <Table.Head class="w-1 px-4"><span class="sr-only">Details</span></Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each items as n (n.message_uuid)}
            <Table.Row
              class="cursor-pointer"
              onclick={() => (selected = n)}
            >
              <Table.Cell
                class="text-muted-foreground w-32 max-w-32 truncate px-4 py-2 font-mono text-xs"
                title={n.message_uuid}
              >
                {n.message_uuid}
              </Table.Cell>
              <Table.Cell class="px-4 py-2 font-mono text-xs">
                {#if n.destination_ancestors.length > 0}
                  <ol
                    class="inline-flex flex-wrap items-center gap-x-1 gap-y-0.5"
                    title={n.destination_uuid}
                  >
                    {#each n.destination_ancestors as a, i (a.workflow_id)}
                      {@const isLast = i === n.destination_ancestors.length - 1}
                      <li class="inline-flex items-center gap-1">
                        <span
                          aria-hidden="true"
                          title={a.status ?? "unknown"}
                          class="inline-block size-1.5 flex-none rounded-full {statusDotClass(a.status)}"
                        ></span>
                        <a
                          href="/workflows/{encodeURIComponent(a.workflow_id)}/"
                          onclick={(e) => e.stopPropagation()}
                          title={a.workflow_id}
                          class="hover:underline {isLast
                            ? 'text-foreground'
                            : 'text-muted-foreground hover:text-foreground'}"
                        >
                          {a.name ?? a.workflow_id}
                        </a>
                      </li>
                      {#if !isLast}
                        <li aria-hidden="true" class="text-muted-foreground/60 inline-flex">
                          <ChevronRight class="size-3" />
                        </li>
                      {/if}
                    {/each}
                  </ol>
                {:else}
                  <a
                    href="/workflows/{encodeURIComponent(n.destination_uuid)}/"
                    onclick={(e) => e.stopPropagation()}
                    title={n.destination_uuid}
                    class="text-muted-foreground hover:text-foreground hover:underline"
                  >
                    {n.destination_uuid}
                  </a>
                {/if}
              </Table.Cell>
              <Table.Cell class="px-4 py-2 font-mono text-xs">
                {n.topic ?? "—"}
              </Table.Cell>
              <Table.Cell class="px-4 py-2">
                {#if n.consumed}
                  <Badge variant="secondary">Consumed</Badge>
                {:else}
                  <Badge class="bg-status-running/15 text-status-running">
                    Pending
                  </Badge>
                {/if}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground px-4 py-2" title={n.created_at}>
                {formatRelative(n.created_at)}
              </Table.Cell>
              <Table.Cell class="px-4 py-2 text-right">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onclick={(e) => {
                    e.stopPropagation();
                    selected = n;
                  }}
                  title="View details"
                  aria-label="View notification details"
                >
                  <Eye />
                </Button>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card.Root>
  {/if}
</div>

<Sheet.Root
  open={selected !== null}
  onOpenChange={(open) => {
    if (!open) selected = null;
  }}
>
  <Sheet.Content
    class="flex w-full flex-col gap-0 p-0 data-[side=right]:sm:max-w-2xl"
  >
    {#if selected}
      <Sheet.Header class="border-border border-b px-6 py-4">
        <Sheet.Title class="flex items-center gap-2 text-base">
          {#if selected.consumed}
            <Badge variant="secondary">Consumed</Badge>
          {:else}
            <Badge class="bg-status-running/15 text-status-running">
              Pending
            </Badge>
          {/if}
          Notification
        </Sheet.Title>
        <Sheet.Description class="text-muted-foreground font-mono text-xs break-all">
          {selected.message_uuid}
        </Sheet.Description>
      </Sheet.Header>

      <div class="flex flex-1 flex-col gap-6 overflow-auto px-6 py-5">
        <dl class="flex flex-col gap-5">
          <div class="flex flex-col gap-1.5">
            <dt
              class="text-muted-foreground text-xs font-medium uppercase tracking-wide"
            >
              Topic
            </dt>
            <dd class="font-mono text-sm">
              {#if selected.topic}
                {selected.topic}
              {:else}
                <span class="text-muted-foreground">—</span>
              {/if}
            </dd>
          </div>

          <div class="flex flex-col gap-1.5">
            <dt
              class="text-muted-foreground text-xs font-medium uppercase tracking-wide"
            >
              Sent
            </dt>
            <dd class="text-sm" title={selected.created_at}>
              {new Date(selected.created_at).toLocaleString()}
              <span class="text-muted-foreground">
                · {formatRelative(selected.created_at)}
              </span>
            </dd>
          </div>

          <div class="flex flex-col gap-1.5">
            <dt
              class="text-muted-foreground text-xs font-medium uppercase tracking-wide"
            >
              Destination
            </dt>
            <dd>
              {#if selected.destination_ancestors.length > 0}
                <ol
                  class="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1"
                  title={selected.destination_uuid}
                >
                  {#each selected.destination_ancestors as a, i (a.workflow_id)}
                    {@const isLast = i === selected.destination_ancestors.length - 1}
                    <li class="inline-flex items-center gap-1.5">
                      <span
                        aria-hidden="true"
                        title={a.status ?? "unknown"}
                        class="inline-block size-1.5 flex-none rounded-full {statusDotClass(a.status)}"
                      ></span>
                      <a
                        href="/workflows/{encodeURIComponent(a.workflow_id)}/"
                        title={a.workflow_id}
                        class="hover:underline {isLast
                          ? 'text-foreground font-medium'
                          : 'text-muted-foreground hover:text-foreground'} text-sm"
                      >
                        {a.name ?? a.workflow_id}
                      </a>
                    </li>
                    {#if !isLast}
                      <li aria-hidden="true" class="text-muted-foreground/60 inline-flex">
                        <ChevronRight class="size-3.5" />
                      </li>
                    {/if}
                  {/each}
                </ol>
                <p
                  class="text-muted-foreground mt-1 font-mono text-xs break-all"
                  title={selected.destination_uuid}
                >
                  {selected.destination_uuid}
                </p>
              {:else}
                <a
                  href="/workflows/{encodeURIComponent(selected.destination_uuid)}/"
                  class="hover:text-foreground hover:underline font-mono text-sm break-all"
                >
                  {selected.destination_uuid}
                </a>
              {/if}
            </dd>
          </div>
        </dl>

        <div class="flex flex-1 flex-col gap-2">
          <div class="flex items-center justify-between gap-2">
            <span class="text-muted-foreground text-xs uppercase tracking-wide">
              Message
            </span>
            <div class="flex items-center gap-2">
              {#if selected.serialization}
                <span
                  class="bg-muted text-muted-foreground inline-flex items-center rounded-full px-1.5 py-0.5 font-mono text-xs font-medium"
                  title="Serialization format (DBOS `serialization` column)"
                >
                  {selected.serialization}
                </span>
              {/if}
              {#if messagePayload.raw}
                <button
                  type="button"
                  onclick={copyMessage}
                  title={justCopied ? "Copied!" : "Copy to clipboard"}
                  aria-label="Copy message"
                  class="text-muted-foreground hover:text-foreground hover:bg-muted flex h-6 w-6 items-center justify-center rounded transition-colors"
                >
                  {#if justCopied}
                    <Check class="text-status-success h-3.5 w-3.5" />
                  {:else}
                    <Copy class="h-3.5 w-3.5" />
                  {/if}
                </button>
                <div class="bg-muted flex items-center rounded-md p-0.5">
                  <button
                    type="button"
                    class="rounded px-2 py-0.5 text-xs font-medium transition
                      {effectiveMode === 'raw'
                        ? 'bg-background text-foreground shadow-xs'
                        : 'text-muted-foreground hover:text-foreground'}"
                    onclick={() => (preferredMode = "raw")}
                  >
                    Raw
                  </button>
                  <button
                    type="button"
                    disabled={messagePayload.decoded === null}
                    class="rounded px-2 py-0.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40
                      {effectiveMode === 'decoded'
                        ? 'bg-background text-foreground shadow-xs'
                        : 'text-muted-foreground enabled:hover:text-foreground'}"
                    onclick={() => (preferredMode = "decoded")}
                    title={messagePayload.decoded === null
                      ? "Server couldn't decode this payload — showing raw"
                      : "Decoded via server-side unpickler / JSON parser"}
                  >
                    Decoded
                  </button>
                </div>
              {/if}
            </div>
          </div>
          {#if messagePayload.raw === null}
            <p class="text-muted-foreground text-sm">No message payload.</p>
          {:else}
            <pre
              class="border-border bg-muted/40 max-h-[60vh] overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words">{displayedMessage}</pre>
            {#if messagePayload.decoded === null && selected.serialization && selected.serialization.toLowerCase().includes("pickle")}
              <p class="text-muted-foreground text-xs">
                Pickled Python value couldn't be decoded safely (likely a custom class).
                Showing the raw on-disk base64 payload.
              </p>
            {/if}
          {/if}
        </div>
      </div>
    {/if}
  </Sheet.Content>
</Sheet.Root>
