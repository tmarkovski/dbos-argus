<script lang="ts">
  import { tick } from "svelte";
  import type { FlowSelection } from "./WorkflowFlow.svelte";
  import { statusBadgeClass } from "$lib/workflow-tree";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import Copy from "@lucide/svelte/icons/copy";
  import Check from "@lucide/svelte/icons/check";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";

  // Result data is loaded lazily by the parent page (cached for the lifetime
  // of the page) so we never drag potentially-large output blobs through
  // the workflow detail response.
  export type ResultData = {
    output: string | null;
    error: string | null;
    serialization: string | null;
    output_decoded: string | null;
    error_decoded: string | null;
  };

  // Events published by a workflow via DBOS.setEvent. Bundled in the workflow
  // detail response, filtered by selected workflow_id below.
  export type EventSet = {
    function_id: number;
    value: string;
    serialization: string | null;
    value_decoded: string | null;
    completed_at: string | null;
  };

  export type WorkflowEventEntry = {
    workflow_id: string;
    key: string;
    value: string;
    serialization: string | null;
    value_decoded: string | null;
    history: EventSet[];
  };

  let {
    selection,
    result,
    loading = false,
    events = [],
  }: {
    selection: FlowSelection;
    result: ResultData | null;
    loading?: boolean;
    events?: WorkflowEventEntry[];
  } = $props();

  type ViewMode = "raw" | "decoded";

  // Preference survives across selections so the user doesn't have to
  // re-toggle every click.
  let preferredMode = $state<ViewMode>("decoded");

  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)}s`;
    const m = s / 60;
    if (m < 60) return `${m.toFixed(1)}m`;
    return `${(m / 60).toFixed(1)}h`;
  }

  const heading = $derived.by(() => {
    if (!selection) return null;
    if (selection.kind === "workflow") {
      const w = selection.workflow;
      const dur =
        new Date(w.updated_at).getTime() - new Date(w.started_at).getTime();
      return {
        resultLabel: "Workflow result",
        title: w.name ?? "—",
        subtitle: w.workflow_id,
        status: w.status,
        startedAt: w.started_at,
        durationMs: dur >= 0 ? dur : null,
      };
    }
    const s = selection.step;
    const dur =
      s.started_at && s.completed_at
        ? new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()
        : null;
    return {
      resultLabel: `Step #${s.function_id} result`,
      title: s.function_name,
      subtitle: s.workflow_id,
      status: null as string | null,
      startedAt: s.started_at,
      durationMs: dur,
    };
  });

  type MetaItem = {
    label: string;
    value: string;
    title?: string;
    href?: string;
  };

  const metadata = $derived.by<MetaItem[]>(() => {
    if (!selection || !heading) return [];
    const items: MetaItem[] = [];
    if (heading.startedAt)
      items.push({
        label: "Started",
        value: new Date(heading.startedAt).toLocaleString(),
        title: heading.startedAt,
      });
    if (heading.durationMs !== null)
      items.push({ label: "Duration", value: formatDuration(heading.durationMs) });
    if (selection.kind === "workflow") {
      const w = selection.workflow;
      if (w.queue_name) items.push({ label: "Queue", value: w.queue_name });
      if (w.executor_id)
        items.push({ label: "Executor", value: w.executor_id, title: w.executor_id });
      if (w.workflow_timeout_ms !== null && w.workflow_timeout_ms !== undefined)
        items.push({ label: "Timeout", value: formatDuration(w.workflow_timeout_ms) });
      if (
        w.recovery_attempts !== null &&
        w.recovery_attempts !== undefined &&
        w.recovery_attempts > 0
      )
        items.push({
          label: "Recoveries",
          value: String(w.recovery_attempts),
          title: "Times this workflow was resumed after an executor crash",
        });
      return items;
    }
    const s = selection.step;
    if (s.child_workflow_id)
      items.push({
        label: "Child",
        value: s.child_workflow_id,
        title: s.child_workflow_id,
        href: `/workflows/${encodeURIComponent(s.child_workflow_id)}/`,
      });
    if (s.event_key) items.push({ label: "Event key", value: s.event_key });
    if (s.sleep_requested_ms !== null)
      items.push({ label: "Requested", value: formatDuration(s.sleep_requested_ms) });
    return items;
  });

  type Payload =
    | { kind: "none" }
    | { kind: "error"; raw: string; decoded: string | null; serialization: string | null }
    | {
        kind: "output";
        raw: string;
        decoded: string | null;
        serialization: string | null;
        label: string;
      };

  // For DBOS.setEvent steps, the operation_outputs row carries no payload
  // (the value lives in workflow_events_history). Surface that historical
  // value as the step's "result" so the user sees what was set without
  // having to navigate to the workflow's events panel.
  const setEventEntry = $derived.by<WorkflowEventEntry | null>(() => {
    if (!selection || selection.kind !== "step") return null;
    const s = selection.step;
    if (s.function_name !== "DBOS.setEvent") return null;
    return (
      events.find(
        (e) =>
          e.workflow_id === s.workflow_id &&
          e.history.some((h) => h.function_id === s.function_id),
      ) ?? null
    );
  });

  const setEventValue = $derived.by(() => {
    if (!setEventEntry || !selection || selection.kind !== "step") return null;
    const fnId = selection.step.function_id;
    return setEventEntry.history.find((h) => h.function_id === fnId) ?? null;
  });

  const payload = $derived.by<Payload>(() => {
    if (!selection) return { kind: "none" };
    if (setEventValue) {
      return {
        kind: "output",
        raw: setEventValue.value,
        decoded: setEventValue.value_decoded,
        serialization: setEventValue.serialization,
        label: "Event value",
      };
    }
    if (!result) return { kind: "none" };
    if (result.error) {
      return {
        kind: "error",
        raw: result.error,
        decoded: result.error_decoded,
        serialization: result.serialization,
      };
    }
    if (result.output !== null) {
      return {
        kind: "output",
        raw: result.output,
        decoded: result.output_decoded,
        serialization: result.serialization,
        label: "Output",
      };
    }
    return { kind: "none" };
  });

  // Only offer "decoded" when the backend actually produced one.
  const effectiveMode = $derived.by<ViewMode>(() => {
    if (payload.kind === "none") return "raw";
    if (preferredMode === "decoded" && payload.decoded !== null) return "decoded";
    return "raw";
  });

  const displayedText = $derived.by(() => {
    if (payload.kind === "none") return "";
    return effectiveMode === "decoded" && payload.decoded !== null
      ? payload.decoded
      : payload.raw;
  });

  let justCopied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  let expanded = $state(false);

  type DocWithVT = Document & {
    startViewTransition: (cb: () => void | Promise<void>) => unknown;
  };

  // Safari ships startViewTransition but its close-side morph flickers (the
  // dialog/overlay ghosts back in during the root cross-fade). Skip the
  // morph when closing on Safari and let bits-ui's default zoom-95 fade-out
  // play instead.
  function isSafari(): boolean {
    if (typeof navigator === "undefined") return false;
    const ua = navigator.userAgent;
    return /^((?!chrome|android).)*safari/i.test(ua);
  }

  // Browser View Transitions API: when supported, wrap the open/close state
  // change so the browser interpolates the snapshots of the side-pane <pre>
  // and the dialog (matched by `view-transition-name: result-output`) — the
  // box visually grows from the small pre into the dialog and back. Firefox
  // (and Safari on close) fall back to the bits-ui zoom-95 default.
  function transitionExpanded(next: boolean) {
    if (next === expanded) return;
    const doc = typeof document !== "undefined" ? document : null;
    const skipVT = !next && isSafari();
    if (doc && "startViewTransition" in doc && !skipVT) {
      (doc as DocWithVT).startViewTransition(async () => {
        expanded = next;
        await tick();
      });
    } else {
      expanded = next;
    }
  }

  async function copyResult() {
    if (!displayedText) return;
    try {
      await navigator.clipboard.writeText(displayedText);
      justCopied = true;
      if (copyTimer) clearTimeout(copyTimer);
      copyTimer = setTimeout(() => (justCopied = false), 1500);
    } catch (e) {
      console.warn("clipboard write failed", e);
    }
  }

  // Events are workflow-scoped state, only shown when a workflow is selected.
  // Step selections drop the panel — the step's own metadata + result
  // already covers what the user is looking at.
  const visibleEvents = $derived.by<WorkflowEventEntry[]>(() => {
    if (!selection || selection.kind !== "workflow") return [];
    return events.filter((e) => e.workflow_id === selection.workflow.workflow_id);
  });

  function eventPreview(value: string, decoded: string | null): string {
    return decoded !== null ? decoded : value;
  }

  function eventDisplay(value: string, decoded: string | null): string {
    return effectiveEventMode === "decoded" && decoded !== null ? decoded : value;
  }

  let openedEvent = $state<WorkflowEventEntry | null>(null);
  let eventPreferredMode = $state<ViewMode>("decoded");
  let eventCopyKey = $state<string | null>(null);
  let eventCopyTimer: ReturnType<typeof setTimeout> | null = null;

  // Tracks which side-pane card is acting as the View Transition anchor.
  // Multiple cards can be visible, so we tag exactly one with the shared
  // `result-event` name — set right before snapshotting (open) and kept
  // through the close so the morph reverses into the same card.
  let pendingEventKey = $state<string | null>(null);

  async function transitionOpenEvent(target: WorkflowEventEntry | null) {
    if ((target?.key ?? null) === (openedEvent?.key ?? null)) return;
    const doc = typeof document !== "undefined" ? document : null;
    // Same Safari treatment as the output dialog: skip morph on close.
    const skipVT = target === null && isSafari();

    pendingEventKey = target ? target.key : (openedEvent?.key ?? null);

    if (doc && "startViewTransition" in doc && !skipVT) {
      // Let the new pendingEventKey land in the DOM so the OLD snapshot
      // has the right card tagged before the browser captures it.
      await tick();
      const transition = (doc as DocWithVT).startViewTransition(async () => {
        openedEvent = target;
        await tick();
      });
      const finished = (transition as { finished?: Promise<unknown> }).finished;
      const clear = () => {
        pendingEventKey = null;
      };
      if (finished && typeof finished.finally === "function") {
        finished.finally(clear);
      } else {
        requestAnimationFrame(() => requestAnimationFrame(clear));
      }
    } else {
      openedEvent = target;
      pendingEventKey = null;
    }
  }

  // Treat the dialog as having a decoded view available if any value (current
  // or any historical entry) decoded successfully — even if some others fell
  // back to raw, the toggle is still meaningful.
  const eventAnyDecoded = $derived.by(() => {
    if (!openedEvent) return false;
    if (openedEvent.value_decoded !== null) return true;
    return openedEvent.history.some((h) => h.value_decoded !== null);
  });

  const effectiveEventMode = $derived.by<ViewMode>(() => {
    if (!openedEvent) return "raw";
    if (eventPreferredMode === "decoded" && eventAnyDecoded) return "decoded";
    return "raw";
  });

  async function copyEventValue(slot: string, value: string, decoded: string | null) {
    const text = eventDisplay(value, decoded);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      eventCopyKey = slot;
      if (eventCopyTimer) clearTimeout(eventCopyTimer);
      eventCopyTimer = setTimeout(() => (eventCopyKey = null), 1500);
    } catch (e) {
      console.warn("clipboard write failed", e);
    }
  }
</script>

<aside class="bg-card flex h-full w-full flex-col overflow-hidden">
  <div class="border-border bg-muted/30 flex min-h-10 items-center gap-2 border-b px-4 py-2.5">
    <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
      {heading?.resultLabel ?? "Result"}
    </span>
  </div>

  {#if !selection || !heading}
    <div class="text-muted-foreground flex flex-1 items-center justify-center p-6 text-sm">
      Select a workflow or step to see its result.
    </div>
  {:else}
    <div class="border-border flex flex-col gap-1 border-b px-4 py-3">
      <div class="flex items-start gap-2">
        <span class="truncate font-mono text-sm font-medium" title={heading.title}>
          {heading.title}
        </span>
        {#if heading.status}
          <Badge class="ml-auto {statusBadgeClass(heading.status)}">
            {heading.status}
          </Badge>
        {/if}
      </div>
      <div class="text-muted-foreground truncate font-mono text-[10px]" title={heading.subtitle}>
        {heading.subtitle}
      </div>
      {#if metadata.length > 0}
        <dl class="mt-4 flex flex-col gap-5">
          {#each metadata as item (item.label)}
            <div class="flex flex-col gap-1.5">
              <dt
                class="text-muted-foreground text-[11px] font-medium uppercase tracking-wide"
              >
                {item.label}
              </dt>
              <dd class="break-all font-mono text-sm">
                {#if item.href}
                  <a href={item.href} class="hover:underline" title={item.title}>
                    {item.value}
                  </a>
                {:else}
                  <span title={item.title}>{item.value}</span>
                {/if}
              </dd>
            </div>
          {/each}
        </dl>
      {/if}
    </div>

    {#if visibleEvents.length > 0}
      <div class="border-border flex flex-col gap-2 border-b px-4 py-3">
        <div class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          Published events
        </div>
        <ul class="flex flex-col gap-1.5">
          {#each visibleEvents as ev (ev.key)}
            <li>
              <button
                type="button"
                onclick={() => transitionOpenEvent(ev)}
                title="Open event details"
                class="border-border bg-muted/30 hover:bg-muted hover:border-primary/50 relative flex w-full flex-col gap-1 rounded-md border px-2.5 py-2 pr-10 text-left transition-colors"
                style:view-transition-name={pendingEventKey === ev.key &&
                openedEvent?.key !== ev.key
                  ? "result-event"
                  : undefined}
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="truncate font-mono text-xs font-medium" title={ev.key}>
                    {ev.key}
                  </span>
                  {#if ev.history.length > 1}
                    <Badge variant="secondary" class="text-[10px]">
                      {ev.history.length} updates
                    </Badge>
                  {/if}
                </div>
                <div
                  class="text-muted-foreground truncate font-mono text-[11px]"
                  title={eventPreview(ev.value, ev.value_decoded)}
                >
                  {eventPreview(ev.value, ev.value_decoded)}
                </div>
                <span
                  aria-hidden="true"
                  class="bg-background/80 text-muted-foreground hover:text-foreground hover:bg-muted border-border/60 absolute right-2 bottom-2 flex h-7 w-7 items-center justify-center rounded-md border shadow-sm backdrop-blur-sm"
                >
                  <Maximize2 class="h-3.5 w-3.5" />
                </span>
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="flex flex-1 flex-col overflow-hidden">
      {#if loading}
        <div class="text-muted-foreground flex flex-1 items-center justify-center p-6 text-sm">
          Loading…
        </div>
      {:else if payload.kind === "none"}
        <div class="text-muted-foreground flex flex-1 items-center justify-center p-6 text-sm">
          No result recorded.
        </div>
      {:else}
        <div class="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
          <div class="flex items-center gap-2">
            <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
              {payload.kind === "error" ? "Error" : payload.label}
            </span>
            {#if payload.serialization}
              <span
                class="bg-muted text-muted-foreground inline-flex items-center rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
                title="Serialization format (DBOS `serialization` column)"
              >
                {payload.serialization}
              </span>
            {/if}
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              onclick={copyResult}
              title={justCopied ? "Copied!" : "Copy to clipboard"}
              aria-label="Copy result"
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
                class="rounded px-2 py-0.5 text-[11px] font-medium transition
                  {effectiveMode === 'raw'
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'}"
                onclick={() => (preferredMode = "raw")}
              >
                Raw
              </button>
              <button
                type="button"
                disabled={payload.decoded === null}
                class="rounded px-2 py-0.5 text-[11px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40
                  {effectiveMode === 'decoded'
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground enabled:hover:text-foreground'}"
                onclick={() => (preferredMode = "decoded")}
                title={payload.decoded === null
                  ? "Server couldn't decode this payload — showing raw"
                  : "Decoded via server-side unpickler / JSON parser"}
              >
                Decoded
              </button>
            </div>
          </div>
        </div>
        <div class="flex-1 overflow-auto px-4 pb-4">
          <button
            type="button"
            onclick={() => {
              if (setEventEntry) {
                transitionOpenEvent(setEventEntry);
              } else {
                transitionExpanded(true);
              }
            }}
            title={setEventEntry ? "Open event details" : "Expand result"}
            aria-label={setEventEntry ? "Open event details" : "Expand result"}
            class="group relative block w-full text-left"
            style:view-transition-name={expanded
              ? undefined
              : setEventEntry
                ? openedEvent
                  ? undefined
                  : "result-event"
                : "result-output"}
          >
            {#if payload.kind === "error"}
              <pre
                class="border-destructive/30 bg-destructive/5 text-destructive group-hover:border-destructive/70 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words transition-colors">{effectiveMode ===
                "decoded" && payload.decoded !== null
                  ? payload.decoded
                  : payload.raw}</pre>
            {:else}
              <pre
                class="border-border bg-muted/40 group-hover:border-primary/50 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words transition-colors">{effectiveMode ===
                "decoded" && payload.decoded !== null
                  ? payload.decoded
                  : payload.raw}</pre>
            {/if}
            <span
              aria-hidden="true"
              class="bg-background/80 text-muted-foreground group-hover:text-foreground group-hover:bg-muted border-border/60 absolute right-2 bottom-2 flex h-7 w-7 items-center justify-center rounded-md border shadow-sm backdrop-blur-sm transition-colors"
            >
              <Maximize2 class="h-3.5 w-3.5" />
            </span>
          </button>
          {#if payload.decoded === null && payload.serialization && payload.serialization.toLowerCase().includes("pickle")}
            <p class="text-muted-foreground mt-2 text-[11px]">
              Pickled Python value couldn't be decoded safely (likely a custom class). Showing
              the raw on-disk base64 payload.
            </p>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</aside>

<Dialog.Root open={expanded} onOpenChange={transitionExpanded}>
  <Dialog.Content
    class="flex max-h-[85vh] w-full flex-col gap-4 sm:max-w-3xl"
    style={expanded ? "view-transition-name: result-output;" : undefined}
  >
    <Dialog.Header>
      <Dialog.Title class="font-mono text-base">{heading?.title ?? ""}</Dialog.Title>
      {#if selection}
        <Dialog.Description>
          {selection.kind === "step" ? `Step #${selection.step.function_id}` : "Workflow"}
        </Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if payload.kind !== "none"}
      <div class="flex min-h-0 flex-1 flex-col gap-2">
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">
            {payload.kind === "error" ? "Error" : payload.label}
          </span>
          {#if payload.serialization}
            <span
              class="bg-muted text-muted-foreground inline-flex items-center rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
              title="Serialization format (DBOS `serialization` column)"
            >
              {payload.serialization}
            </span>
          {/if}
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            onclick={copyResult}
            title={justCopied ? "Copied!" : "Copy to clipboard"}
            aria-label="Copy result"
            class="text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 w-7 items-center justify-center rounded transition-colors"
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
              class="rounded px-2 py-0.5 text-[11px] font-medium transition
                {effectiveMode === 'raw'
                  ? 'bg-background text-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground'}"
              onclick={() => (preferredMode = "raw")}
            >
              Raw
            </button>
            <button
              type="button"
              disabled={payload.decoded === null}
              class="rounded px-2 py-0.5 text-[11px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40
                {effectiveMode === 'decoded'
                  ? 'bg-background text-foreground shadow-xs'
                  : 'text-muted-foreground enabled:hover:text-foreground'}"
              onclick={() => (preferredMode = "decoded")}
            >
              Decoded
            </button>
          </div>
        </div>
      </div>
      <div class="min-h-0 flex-1 overflow-auto">
        {#if payload.kind === "error"}
          <pre
            class="border-destructive/30 bg-destructive/5 text-destructive overflow-auto rounded-lg border p-4 font-mono text-xs whitespace-pre-wrap break-words">{displayedText}</pre>
        {:else}
          <pre
            class="border-border bg-muted/40 overflow-auto rounded-lg border p-4 font-mono text-xs whitespace-pre-wrap break-words">{displayedText}</pre>
        {/if}
      </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={openedEvent !== null}
  onOpenChange={(v) => {
    if (!v) transitionOpenEvent(null);
  }}
>
  <Dialog.Content
    class="flex max-h-[85vh] w-full flex-col gap-4 sm:max-w-3xl"
    onOpenAutoFocus={(e) => e.preventDefault()}
    style={openedEvent ? "view-transition-name: result-event;" : undefined}
  >
    {#if openedEvent}
      <Dialog.Header>
        <Dialog.Title class="font-mono text-base">{openedEvent.key}</Dialog.Title>
        <Dialog.Description>
          {openedEvent.history.length === 1
            ? "Event set once"
            : `Event set ${openedEvent.history.length} times`}
        </Dialog.Description>
      </Dialog.Header>
      <div class="flex flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">
              Current value
            </span>
            {#if openedEvent.serialization}
              <span
                class="bg-muted text-muted-foreground inline-flex items-center rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
                title="Serialization format (DBOS `serialization` column)"
              >
                {openedEvent.serialization}
              </span>
            {/if}
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              onclick={() =>
                openedEvent &&
                copyEventValue("current", openedEvent.value, openedEvent.value_decoded)}
              title={eventCopyKey === "current" ? "Copied!" : "Copy to clipboard"}
              aria-label="Copy current value"
              class="text-muted-foreground hover:text-foreground hover:bg-muted flex h-6 w-6 items-center justify-center rounded transition-colors"
            >
              {#if eventCopyKey === "current"}
                <Check class="text-status-success h-3.5 w-3.5" />
              {:else}
                <Copy class="h-3.5 w-3.5" />
              {/if}
            </button>
            <div class="bg-muted flex items-center rounded-md p-0.5">
              <button
                type="button"
                class="rounded px-2 py-0.5 text-[11px] font-medium transition
                  {effectiveEventMode === 'raw'
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'}"
                onclick={() => (eventPreferredMode = "raw")}
              >
                Raw
              </button>
              <button
                type="button"
                disabled={!eventAnyDecoded}
                class="rounded px-2 py-0.5 text-[11px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40
                  {effectiveEventMode === 'decoded'
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground enabled:hover:text-foreground'}"
                onclick={() => (eventPreferredMode = "decoded")}
                title={eventAnyDecoded
                  ? "Decoded via server-side unpickler / JSON parser"
                  : "Server couldn't decode any values — only raw available"}
              >
                Decoded
              </button>
            </div>
          </div>
        </div>
        <pre
          class="border-border bg-muted/40 max-h-48 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words">{eventDisplay(
            openedEvent.value,
            openedEvent.value_decoded,
          )}</pre>
      </div>
      {#if openedEvent.history.length > 0}
        <div class="flex min-h-0 flex-1 flex-col gap-2">
          <div class="text-muted-foreground text-[11px] font-medium uppercase tracking-wide">
            History
          </div>
          <ol class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
            {#each openedEvent.history as h (h.function_id)}
              <li class="flex flex-col gap-1.5">
                <div class="text-muted-foreground flex items-center gap-2 text-[11px]">
                  <span class="font-mono">Step #{h.function_id}</span>
                  {#if h.completed_at}
                    <span title={h.completed_at}>
                      · {new Date(h.completed_at).toLocaleString()}
                    </span>
                  {/if}
                </div>
                <pre
                  class="border-border bg-muted/40 max-h-48 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words">{eventDisplay(
                    h.value,
                    h.value_decoded,
                  )}</pre>
              </li>
            {/each}
          </ol>
        </div>
      {/if}
    {/if}
  </Dialog.Content>
</Dialog.Root>
