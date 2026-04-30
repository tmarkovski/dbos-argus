<script lang="ts">
  import type { FlowSelection } from "./WorkflowFlow.svelte";
  import { statusBadgeClass } from "$lib/workflow-tree";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import Copy from "@lucide/svelte/icons/copy";
  import Check from "@lucide/svelte/icons/check";

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

  let {
    selection,
    result,
    loading = false,
  }: {
    selection: FlowSelection;
    result: ResultData | null;
    loading?: boolean;
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
        eyebrow: "Workflow",
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
      eyebrow: `Step #${s.function_id}`,
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
    | { kind: "output"; raw: string; decoded: string | null; serialization: string | null };

  const payload = $derived.by<Payload>(() => {
    if (!selection || !result) return { kind: "none" };
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
</script>

<aside class="bg-card flex h-full w-full flex-col overflow-hidden">
  <div class="border-border bg-muted/30 flex min-h-10 items-center gap-2 border-b px-4 py-2.5">
    <span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
      Result
    </span>
    {#if payload.kind !== "none" && payload.serialization}
      <span
        class="bg-muted text-muted-foreground ml-auto inline-flex items-center rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium"
        title="Serialization format (DBOS `serialization` column)"
      >
        {payload.serialization}
      </span>
    {/if}
  </div>

  {#if !selection || !heading}
    <div class="text-muted-foreground flex flex-1 items-center justify-center p-6 text-sm">
      Select a workflow or step to see its result.
    </div>
  {:else}
    <div class="border-border flex flex-col gap-1 border-b px-4 py-3">
      <div class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
        {heading.eyebrow}
      </div>
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
          <span class="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
            {payload.kind === "error" ? "Error" : "Output"}
          </span>
          <div class="flex items-center gap-2">
            <button
              type="button"
              onclick={copyResult}
              title={justCopied ? "Copied!" : "Copy to clipboard"}
              aria-label="Copy result"
              class="text-muted-foreground hover:text-foreground hover:bg-muted flex h-6 w-6 items-center justify-center rounded transition-colors"
            >
              {#if justCopied}
                <Check class="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
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
          {#if payload.kind === "error"}
            <pre
              class="border-destructive/30 bg-destructive/5 text-destructive overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words">{effectiveMode ===
              "decoded" && payload.decoded !== null
                ? payload.decoded
                : payload.raw}</pre>
          {:else}
            <pre
              class="border-border bg-muted/40 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap break-words">{effectiveMode ===
              "decoded" && payload.decoded !== null
                ? payload.decoded
                : payload.raw}</pre>
          {/if}
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
