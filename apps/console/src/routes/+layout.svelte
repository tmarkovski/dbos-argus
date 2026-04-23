<script lang="ts">
  import "../app.css";
  import { onDestroy, onMount } from "svelte";

  let { children } = $props();

  type Health = {
    status: string;
    database: string;
    database_url?: string;
    database_error?: string;
  };

  let health = $state<Health | null>(null);
  let fetchError = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;

  async function refresh() {
    try {
      const res = await fetch("/healthz");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      health = (await res.json()) as Health;
      fetchError = null;
    } catch (e) {
      health = null;
      fetchError = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  const dbConnected = $derived(!fetchError && health?.database === "up");
  const label = $derived(dbConnected ? "Connected" : "Disconnected");
  const detail = $derived(
    dbConnected
      ? (health?.database_url ?? "")
      : (fetchError ?? health?.database_error ?? ""),
  );
</script>

<div class="flex min-h-screen flex-col">
  <nav
    class="flex items-center justify-between border-b border-neutral-200 bg-white px-6 py-3"
  >
    <a href="/" class="text-lg font-semibold hover:text-neutral-600">Argus</a>
    <span class="flex flex-col items-end text-sm leading-tight">
      <span class="flex items-center gap-2">
        <span
          aria-hidden="true"
          class="inline-block h-2.5 w-2.5 rounded-full {dbConnected
            ? 'bg-green-500'
            : 'bg-red-500'}"
        ></span>
        <span class="text-neutral-700">{label}</span>
      </span>
      {#if detail}
        <span
          class="mt-0.5 max-w-md truncate font-mono text-xs text-neutral-400"
          title={detail}>{detail}</span
        >
      {/if}
    </span>
  </nav>
  <main class="flex-1">
    {@render children()}
  </main>
</div>
