<script lang="ts">
  import "../app.css";
  import { onDestroy, onMount } from "svelte";
  import Sun from "@lucide/svelte/icons/sun";
  import Moon from "@lucide/svelte/icons/moon";
  import House from "@lucide/svelte/icons/house";
  import Eye from "@lucide/svelte/icons/eye";
  import Workflow from "@lucide/svelte/icons/workflow";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import Bell from "@lucide/svelte/icons/bell";
  import { page } from "$app/state";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import { statusDotClass } from "$lib/workflow-tree";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import * as Breadcrumb from "$lib/components/ui/breadcrumb/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";

  let { children } = $props();

  type NavItem = {
    href: string;
    label: string;
    icon: typeof Workflow;
  };

  const NAV: NavItem[] = [
    { href: "/workflows/", label: "Workflows", icon: Workflow },
    { href: "/schedules/", label: "Schedules", icon: CalendarClock },
    { href: "/notifications/", label: "Notifications", icon: Bell },
  ];

  const pathname = $derived(page.url.pathname);
  function isActive(href: string): boolean {
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
  const dbLabel = $derived(dbConnected ? "Connected" : "Disconnected");
  const dbDetail = $derived(
    dbConnected
      ? (health?.database_url ?? "")
      : (fetchError ?? health?.database_error ?? ""),
  );
</script>

<Sidebar.Provider>
  <Sidebar.Root collapsible="icon" variant="inset">
    <Sidebar.Header>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton size="lg" class="data-[slot=sidebar-menu-button]:!p-1.5">
            {#snippet child({ props })}
              <a href="/" {...props}>
                <div
                  class="bg-sidebar-primary text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg"
                >
                  <Eye class="size-4" />
                </div>
                <div class="grid flex-1 text-left text-sm leading-tight">
                  <span class="truncate font-semibold">Argus</span>
                  <span class="text-muted-foreground truncate text-xs">
                    DBOS Workflow Viewer
                  </span>
                </div>
              </a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Header>

    <Sidebar.Content>
      <Sidebar.Group>
        <Sidebar.GroupLabel>Navigation</Sidebar.GroupLabel>
        <Sidebar.GroupContent>
          <Sidebar.Menu>
            {#each NAV as item (item.href)}
              <Sidebar.MenuItem>
                <Sidebar.MenuButton
                  isActive={isActive(item.href)}
                  tooltipContent={item.label}
                >
                  {#snippet child({ props })}
                    <a href={item.href} {...props}>
                      <item.icon />
                      <span>{item.label}</span>
                    </a>
                  {/snippet}
                </Sidebar.MenuButton>
              </Sidebar.MenuItem>
            {/each}
          </Sidebar.Menu>
        </Sidebar.GroupContent>
      </Sidebar.Group>
    </Sidebar.Content>

    <Sidebar.Footer>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton
            tooltipContent={dbDetail || dbLabel}
            class="cursor-default"
          >
            <span
              aria-hidden="true"
              class="inline-block size-2 shrink-0 rounded-full {dbConnected
                ? 'bg-green-500'
                : 'bg-red-500'}"
            ></span>
            <span class="flex flex-1 flex-col leading-tight">
              <span class="text-foreground text-xs font-medium">{dbLabel}</span>
              {#if dbDetail}
                <span class="text-muted-foreground truncate font-mono text-[10px]">
                  {dbDetail}
                </span>
              {/if}
            </span>
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton
            onclick={toggleTheme}
            tooltipContent={isDark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {#if isDark}
              <Sun />
              <span>Light mode</span>
            {:else}
              <Moon />
              <span>Dark mode</span>
            {/if}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Footer>

    <Sidebar.Rail />
  </Sidebar.Root>

  <Sidebar.Inset>
    <header
      class="bg-background sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b px-4 md:rounded-t-xl"
    >
      <Sidebar.Trigger class="-ml-1" />
      <Separator orientation="vertical" class="mr-2 !h-4" />
      <Breadcrumb.Root>
        <Breadcrumb.List>
          {#each breadcrumb.items as item, i (i)}
            {#if i > 0}
              <Breadcrumb.Separator />
            {/if}
            <Breadcrumb.Item class="inline-flex items-center gap-1.5">
              {#if item.status !== undefined}
                <span
                  aria-hidden="true"
                  title={item.status ?? "unknown"}
                  class="inline-block size-2 flex-none rounded-full {statusDotClass(item.status)}"
                ></span>
              {/if}
              {#if item.href && i !== breadcrumb.items.length - 1}
                <Breadcrumb.Link
                  href={item.href}
                  title={item.tooltip}
                  aria-label={item.icon ? item.label : undefined}
                  class="inline-flex items-center"
                >
                  {#if item.icon === "home"}
                    <House class="size-3.5" />
                  {:else}
                    {item.label}
                  {/if}
                </Breadcrumb.Link>
              {:else}
                <Breadcrumb.Page title={item.tooltip} class="inline-flex items-center">
                  {#if item.icon === "home"}
                    <House class="size-3.5" />
                  {:else}
                    {item.label}
                  {/if}
                </Breadcrumb.Page>
              {/if}
            </Breadcrumb.Item>
          {/each}
        </Breadcrumb.List>
      </Breadcrumb.Root>
    </header>
    <div class="flex flex-1 flex-col">
      {@render children()}
    </div>
  </Sidebar.Inset>
</Sidebar.Provider>
