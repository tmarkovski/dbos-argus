<script lang="ts">
  import "../app.css";
  import { onDestroy, onMount } from "svelte";
  import Sun from "@lucide/svelte/icons/sun";
  import Moon from "@lucide/svelte/icons/moon";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import House from "@lucide/svelte/icons/house";
  import { page } from "$app/state";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { statusDotClass } from "$lib/workflow-tree";

  let { children } = $props();

  const NAV: { href: string; label: string }[] = [
    { href: "/workflows/", label: "Workflows" },
    { href: "/queues/", label: "Queues" },
    { href: "/schedules/", label: "Schedules" },
    { href: "/notifications/", label: "Notifications" },
  ];

  const pathname = $derived(page.url.pathname);
  function isActive(href: string): boolean {
    // Strip trailing slash for comparison; route trailingSlash is "always".
    const base = href.replace(/\/$/, "");
    return pathname === href || pathname === base || pathname.startsWith(base + "/");
  }

  type Health = {
    status: string;
    database: string;
    database_url?: string;
    database_error?: string;
  };

  let health = $state<Health | null>(null);
  let fetchError = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | undefined;
  let isDark = $state(false);

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
    isDark = document.documentElement.classList.contains("dark");
    refresh();
    timer = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });

  function toggleTheme() {
    isDark = !isDark;
    document.documentElement.classList.toggle("dark", isDark);
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch (_) {
      // ignore storage failures (private mode etc)
    }
  }

  const dbConnected = $derived(!fetchError && health?.database === "up");
  const label = $derived(dbConnected ? "Connected" : "Disconnected");
  const detail = $derived(
    dbConnected
      ? (health?.database_url ?? "")
      : (fetchError ?? health?.database_error ?? ""),
  );
</script>

<div class="bg-background text-foreground flex min-h-screen flex-col">
  <nav
    class="border-border bg-background flex items-center justify-between border-b px-6 py-3"
  >
    <div class="flex flex-col items-start gap-1">
      <div class="flex items-center gap-4">
        <a href="/" class="text-foreground hover:text-muted-foreground text-lg font-semibold">
          Argus for DBOS Workflows
        </a>
        <nav class="flex items-center gap-1 text-sm">
          {#each NAV as item (item.href)}
            <a
              href={item.href}
              class="rounded-md px-2.5 py-1 transition-colors {isActive(item.href)
                ? 'bg-muted text-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'}"
            >
              {item.label}
            </a>
          {/each}
        </nav>
        <button
          type="button"
          onclick={toggleTheme}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
          aria-label="Toggle color theme"
          class="text-muted-foreground hover:text-foreground hover:bg-muted flex h-8 w-8 items-center justify-center rounded-md transition-colors"
        >
          {#if isDark}
            <Sun class="h-4 w-4" />
          {:else}
            <Moon class="h-4 w-4" />
          {/if}
        </button>
      </div>
      {#if breadcrumb.items.length > 0}
        <nav
          aria-label="Breadcrumb"
          class="text-muted-foreground flex items-center gap-1 font-mono text-xs"
        >
          {#each breadcrumb.items as item, i (i)}
            {#if i > 0}
              <ChevronRight class="h-3 w-3 flex-none opacity-60" aria-hidden="true" />
            {/if}
            <span class="inline-flex items-center gap-1.5">
              {#if item.status !== undefined}
                <span
                  aria-hidden="true"
                  title={item.status ?? "unknown"}
                  class="inline-block h-2 w-2 flex-none rounded-full {statusDotClass(item.status)}"
                ></span>
              {/if}
              {#if item.href && i !== breadcrumb.items.length - 1}
                <a
                  href={item.href}
                  class="hover:text-foreground inline-flex items-center transition-colors"
                  title={item.tooltip}
                  aria-label={item.icon ? item.label : undefined}
                >
                  {#if item.icon === "home"}
                    <House class="h-3.5 w-3.5" />
                  {:else}
                    {item.label}
                  {/if}
                </a>
              {:else}
                <span class="text-foreground inline-flex items-center" title={item.tooltip}>
                  {#if item.icon === "home"}
                    <House class="h-3.5 w-3.5" />
                  {:else}
                    {item.label}
                  {/if}
                </span>
              {/if}
            </span>
          {/each}
        </nav>
      {/if}
    </div>
    <span class="flex flex-col items-end text-sm leading-tight">
      <span class="flex items-center gap-2">
        <span
          aria-hidden="true"
          class="inline-block h-2.5 w-2.5 rounded-full {dbConnected
            ? 'bg-green-500'
            : 'bg-red-500'}"
        ></span>
        <span class="text-foreground">{label}</span>
      </span>
      {#if detail}
        <span
          class="text-muted-foreground mt-0.5 max-w-md truncate font-mono text-xs"
          title={detail}>{detail}</span
        >
      {/if}
    </span>
  </nav>
  <main class="flex-1">
    {@render children()}
  </main>
</div>
