<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { breadcrumb } from "$lib/breadcrumb.svelte";

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
  let timer: ReturnType<typeof setInterval> | undefined;

  $effect(() => {
    breadcrumb.items = [
      { label: "Home", href: "/", icon: "home" },
      { label: "Schedules" },
    ];
    return () => {
      breadcrumb.items = [];
    };
  });

  async function refresh() {
    try {
      const res = await fetch("/api/schedules");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      schedules = (await res.json()) as WorkflowSchedule[];
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      schedules = null;
    }
  }

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 10000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  function statusClass(status: string): string {
    if (status === "ACTIVE")
      return "bg-green-100 text-green-800 ring-green-600/20 dark:bg-green-500/10 dark:text-green-400";
    return "bg-muted text-muted-foreground ring-border";
  }
</script>

<div class="flex flex-col gap-4 p-6">
  <header class="flex items-baseline justify-between">
    <h1 class="text-lg font-semibold">Schedules</h1>
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
    <div class="border-border bg-card overflow-hidden rounded-lg border shadow-xs">
      <table class="w-full text-left text-sm">
        <thead class="bg-muted/50 text-muted-foreground text-xs tracking-wide uppercase">
          <tr>
            <th class="px-4 py-2 font-medium">Status</th>
            <th class="px-4 py-2 font-medium">Name</th>
            <th class="px-4 py-2 font-medium">Workflow</th>
            <th class="px-4 py-2 font-medium">Schedule</th>
            <th class="px-4 py-2 font-medium">Timezone</th>
            <th class="px-4 py-2 font-medium">Queue</th>
            <th class="px-4 py-2 font-medium">Last fired</th>
          </tr>
        </thead>
        <tbody>
          {#each schedules as s (s.schedule_id)}
            <tr class="hover:bg-muted/50 border-border border-t">
              <td class="px-4 py-2">
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset {statusClass(
                    s.status,
                  )}"
                >
                  {s.status}
                </span>
              </td>
              <td class="px-4 py-2 font-mono">{s.schedule_name}</td>
              <td class="px-4 py-2 font-mono text-xs" title={s.workflow_class_name ?? ""}>
                {#if s.workflow_class_name}
                  <span class="text-muted-foreground">{s.workflow_class_name}.</span>
                {/if}{s.workflow_name}
              </td>
              <td class="px-4 py-2 font-mono text-xs">{s.schedule}</td>
              <td class="text-muted-foreground px-4 py-2 text-xs">
                {s.cron_timezone ?? "UTC"}
              </td>
              <td class="text-muted-foreground px-4 py-2 font-mono text-xs">
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
              </td>
              <td class="text-muted-foreground px-4 py-2 text-xs" title={s.last_fired_at ?? ""}>
                {s.last_fired_at ?? "—"}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
