<script lang="ts">
  import "../app.css";
  import { onDestroy, onMount } from "svelte";
  import Sun from "@lucide/svelte/icons/sun";
  import Moon from "@lucide/svelte/icons/moon";
  import House from "@lucide/svelte/icons/house";
  import Eye from "@lucide/svelte/icons/eye";
  import Workflow from "@lucide/svelte/icons/workflow";
  import Database from "@lucide/svelte/icons/database";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import Layers from "@lucide/svelte/icons/layers";
  import Bell from "@lucide/svelte/icons/bell";
  import { page } from "$app/state";
  import { breadcrumb } from "$lib/breadcrumb.svelte";
  import {
    connectionIndicatorClass,
    connectionIndicatorLabel,
    diagnosticsIssueSummary,
    formatDialectLabel,
    getConnectionIndicatorState,
  } from "$lib/connection-diagnostics";
  import { connectionState } from "$lib/connection-state.svelte";
  import { statsState } from "$lib/stats.svelte";
  import { statusDotClass } from "$lib/workflow-tree";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import * as Breadcrumb from "$lib/components/ui/breadcrumb/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import GithubLink from "$lib/components/GithubLink.svelte";

  let { children } = $props();

  type Pill = { count: number; class: string; dotClass: string; label: string };
  type NavItem = {
    href: string;
    label: string;
    icon: typeof Workflow;
    badges?: () => Pill[];
  };

  const PILL_RUNNING = "bg-status-running/15 text-status-running";
  const PILL_QUEUED = "bg-status-queued/15 text-status-queued";

  const NAV: NavItem[] = [
    { href: "/", label: "Dashboard", icon: House },
    {
      href: "/workflows/",
      label: "Workflows",
      icon: Workflow,
      badges: () => {
        const s = statsState.data;
        if (!s) return [];
        // in_flight already includes ENQUEUED — split so the two counts don't
        // double-count each other.
        const running = Math.max(0, s.in_flight - s.enqueued);
        return [
          { count: running, class: PILL_RUNNING, dotClass: "bg-status-running", label: "Running" },
          { count: s.enqueued, class: PILL_QUEUED, dotClass: "bg-status-queued", label: "Queued" },
        ];
      },
    },
    { href: "/queues/", label: "Queues", icon: Layers },
    { href: "/schedules/", label: "Schedules", icon: CalendarClock },
    {
      href: "/notifications/",
      label: "Notifications",
      icon: Bell,
      badges: () => {
        const n = statsState.data?.pending_notifications;
        if (n == null) return [];
        return [
          { count: n, class: PILL_RUNNING, dotClass: "bg-status-running", label: "Pending" },
        ];
      },
    },
  ];

  function formatBadge(n: number): string {
    return n > 99 ? "99+" : String(n);
  }

  const pathname = $derived(page.url.pathname);
  function isActive(href: string): boolean {
    // The Home link points at "/" — every other path starts with "/", so it
    // would otherwise match everywhere. Treat root as exact-match-only.
    if (href === "/") return pathname === "/";
    const base = href.replace(/\/$/, "");
    return pathname === href || pathname === base || pathname.startsWith(base + "/");
  }

  let isDark = $state(false);
  // Sidebar collapsed/expanded state survives reloads. SSR has no window, so
  // we default to expanded and correct on hydrate. The shadcn provider also
  // writes a cookie, but localStorage is what we read on the client to avoid
  // a flash of mismatched state on slow first paint.
  const SIDEBAR_OPEN_KEY = "argus.sidebar.open";
  let sidebarOpen = $state(true);

  onMount(() => {
    isDark = document.documentElement.classList.contains("dark");
    try {
      const saved = localStorage.getItem(SIDEBAR_OPEN_KEY);
      if (saved !== null) sidebarOpen = saved === "1";
    } catch {
      // localStorage may be unavailable (private mode, sandboxed) — fall
      // back to the default expanded state.
    }
    // Realtime subscriptions: the server pushes health + stats; no client
    // polling needed. Diagnostics auto-fetch from connectionState once the
    // first up-health snapshot lands.
    connectionState.start();
    statsState.start();
  });

  function persistSidebarOpen(value: boolean) {
    try {
      localStorage.setItem(SIDEBAR_OPEN_KEY, value ? "1" : "0");
    } catch {
      // see onMount note
    }
  }

  onDestroy(() => {
    connectionState.stop();
    statsState.stop();
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

  const dbIndicatorState = $derived(
    getConnectionIndicatorState({
      fetchError: connectionState.fetchError,
      health: connectionState.health,
      diagnostics: connectionState.diagnostics,
    }),
  );
  const dbConnected = $derived(dbIndicatorState !== "disconnected");
  const dbLabel = $derived(connectionIndicatorLabel(dbIndicatorState));
  const dbIconClass = $derived(connectionIndicatorClass(dbIndicatorState));
  const dbIssueSummary = $derived(diagnosticsIssueSummary(connectionState.diagnostics));
  const dbSubtitle = $derived.by(() => {
    if (dbIndicatorState === "connected") {
      return formatDialectLabel(
        connectionState.health?.database_dialect,
        connectionState.health?.database_version,
      );
    }
    if (dbIndicatorState === "issues") return dbIssueSummary ?? "Schema mismatch detected";
    return "Database unavailable";
  });
  const dbDetail = $derived(
    dbConnected
      ? (connectionState.health?.database_url ?? "")
      : (connectionState.fetchError ?? connectionState.health?.database_error ?? ""),
  );
  const dbDescription = $derived.by(() => {
    if (!dbConnected) return "The DB connection is currently unavailable.";
    const dialect = connectionState.health?.database_dialect;
    if (dialect === "postgres") return "Read-only connection to the DBOS Postgres database.";
    if (dialect === "sqlite") return "Read-only connection to the DBOS SQLite database.";
    return "Read-only connection to the DBOS database.";
  });
  const dbType = $derived(
    formatDialectLabel(
      connectionState.health?.database_dialect,
      connectionState.health?.database_version,
    ),
  );
  const dbSchemaRev = $derived(connectionState.health?.dbos_schema_revision ?? null);
</script>

<Sidebar.Provider bind:open={sidebarOpen} onOpenChange={persistSidebarOpen}>
  <Sidebar.Root collapsible="icon" variant="sidebar">
    <Sidebar.Header>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton size="lg">
            {#snippet child({ props })}
              <a href="/" {...props}>
                <div
                  class="bg-primary text-primary-foreground flex aspect-square size-8 items-center justify-center rounded-full"
                >
                  <Eye class="size-4" />
                </div>
                <div class="flex flex-1 flex-col gap-0.5 text-left text-sm leading-snug">
                  <span class="truncate font-medium">Argus</span>
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
        <Sidebar.GroupContent>
          <Sidebar.Menu class="gap-1">
            {#each NAV as item (item.href)}
              {@const allBadges = item.badges?.() ?? []}
              {@const pills = allBadges.filter((p) => p.count > 0)}
              {@const useUnderLabels = allBadges.length > 1 && pills.length > 0}
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
                {#if pills.length > 0 && !useUnderLabels}
                  <Sidebar.MenuBadge
                    class="top-1/2! right-2 -translate-y-1/2 {pills[0].class}"
                    title={pills[0].label}
                  >
                    {formatBadge(pills[0].count)}
                  </Sidebar.MenuBadge>
                {/if}
                {#if useUnderLabels}
                  <div
                    class="mt-0.5 flex flex-col group-data-[collapsible=icon]:hidden"
                  >
                    {#each pills as pill (pill.label)}
                      <div
                        class="text-muted-foreground flex h-6 items-center justify-between pr-2 pl-9 text-xs"
                      >
                        <span>{pill.label}</span>
                        <span
                          class="flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-xs font-medium tabular-nums select-none {pill.class}"
                        >
                          {formatBadge(pill.count)}
                        </span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </Sidebar.MenuItem>
            {/each}
          </Sidebar.Menu>
        </Sidebar.GroupContent>
      </Sidebar.Group>
    </Sidebar.Content>

    <Sidebar.Footer>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sheet.Root bind:open={connectionState.sheetOpen}>
            <Sheet.Trigger>
              {#snippet child({ props })}
                <Sidebar.MenuButton
                  size="lg"
                  tooltipContent="Connection details"
                  class="h-auto min-h-12 items-start py-2"
                  {...props}
                >
                  <Database
                    class="self-start group-data-[collapsible=icon]:self-center {dbIconClass}"
                  />
                  <div
                    class="flex min-w-0 flex-1 flex-col gap-0.5 text-left text-sm leading-snug group-data-[collapsible=icon]:hidden"
                  >
                    <span class="truncate font-medium {dbIconClass}">{dbLabel}</span>
                    <span class="text-muted-foreground truncate text-xs" title={dbSubtitle}>
                      {dbSubtitle}
                    </span>
                    {#if dbDetail}
                      <span
                        class="text-muted-foreground/80 truncate font-mono text-xs"
                        title={dbDetail}
                      >
                        {dbDetail}
                      </span>
                    {/if}
                  </div>
                </Sidebar.MenuButton>
              {/snippet}
            </Sheet.Trigger>
            <Sheet.Content
              class="flex w-full flex-col gap-0 p-0 data-[side=right]:sm:max-w-4xl"
            >
              <Sheet.Header class="border-border border-b px-6 py-4">
                <Sheet.Title class="flex items-center gap-2 text-base">
                  <Database class="size-4 {dbIconClass}" />
                  {dbLabel}
                </Sheet.Title>
                <Sheet.Description>{dbDescription}</Sheet.Description>
              </Sheet.Header>
              <div class="flex flex-1 flex-col gap-6 overflow-auto px-6 py-4">
                {#if dbDetail}
                  <div class="flex flex-col gap-1.5">
                    <span class="text-muted-foreground text-xs uppercase tracking-wide">
                      {dbConnected ? "URL" : "Error"}
                    </span>
                    <p class="text-muted-foreground font-mono text-xs break-all">
                      {dbDetail}
                    </p>
                  </div>
                {/if}

                {#if dbConnected && (dbType || dbSchemaRev)}
                  <dl class="grid grid-cols-2 gap-4">
                    {#if dbType}
                      <div class="flex flex-col gap-1.5">
                        <dt
                          class="text-muted-foreground text-xs uppercase tracking-wide"
                        >
                          Database
                        </dt>
                        <dd class="font-mono text-xs">{dbType}</dd>
                      </div>
                    {/if}
                    {#if dbSchemaRev}
                      <div class="flex flex-col gap-1.5">
                        <dt
                          class="text-muted-foreground text-xs uppercase tracking-wide"
                        >
                          DBOS schema revision
                        </dt>
                        <dd class="font-mono text-xs">{dbSchemaRev}</dd>
                      </div>
                    {/if}
                  </dl>
                {/if}

                {#if dbConnected}
                  <div class="flex flex-col gap-3">
                    <div class="flex flex-col gap-1.5">
                      <span class="text-muted-foreground text-xs uppercase tracking-wide">
                        SQL diagnostics
                      </span>
                      <p class="text-muted-foreground text-sm">
                        Checks the DBOS tables and columns Argus currently queries.
                      </p>
                    </div>

                    {#if connectionState.diagnosticsLoading}
                      <p class="text-muted-foreground text-sm">Checking the dbos schema…</p>
                    {:else if connectionState.diagnosticsError}
                      <p class="text-destructive text-sm">{connectionState.diagnosticsError}</p>
                    {:else if connectionState.diagnostics}
                      {#if connectionState.diagnostics.ok}
                        <p class="text-sm">
                          No missing tables, missing columns, or type mismatches were detected.
                        </p>
                      {:else}
                        <div class="overflow-x-auto rounded-lg border">
                          <Table.Root>
                            <Table.Header class="bg-muted/40">
                              <Table.Row class="hover:bg-muted/40">
                                <Table.Head class="px-4">Problem</Table.Head>
                                <Table.Head class="px-4">Object</Table.Head>
                                <Table.Head class="px-4">Expected</Table.Head>
                                <Table.Head class="px-4">Actual</Table.Head>
                              </Table.Row>
                            </Table.Header>
                            <Table.Body>
                              {#each connectionState.diagnostics.issues as issue, i (`${issue.table_name}:${issue.column_name ?? 'table'}:${i}`)}
                                <Table.Row>
                                  <Table.Cell class="px-4 py-2 align-top">
                                    {issue.kind === "missing_table"
                                      ? "Missing table"
                                      : issue.kind === "missing_column"
                                        ? "Missing column"
                                        : "Wrong type"}
                                  </Table.Cell>
                                  <Table.Cell class="px-4 py-2 font-mono text-xs align-top">
                                    dbos.{issue.table_name}{issue.column_name
                                      ? `.${issue.column_name}`
                                      : ""}
                                  </Table.Cell>
                                  <Table.Cell class="px-4 py-2 font-mono text-xs align-top">
                                    {issue.expected_type ?? "—"}
                                  </Table.Cell>
                                  <Table.Cell class="px-4 py-2 font-mono text-xs align-top">
                                    {issue.actual_type ?? "—"}
                                  </Table.Cell>
                                </Table.Row>
                              {/each}
                            </Table.Body>
                          </Table.Root>
                        </div>
                        <div class="flex flex-col gap-1.5">
                          <span class="text-muted-foreground text-xs uppercase tracking-wide">
                            Note
                          </span>
                          <p class="text-muted-foreground text-sm">
                            This is likely due to an older version of DBOS than Argus currently
                            expects.
                          </p>
                        </div>
                      {/if}
                    {/if}
                  </div>
                {/if}
              </div>
            </Sheet.Content>
          </Sheet.Root>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Footer>
  </Sidebar.Root>

  <Sidebar.Inset>
    <header
      class="bg-background sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b px-4"
    >
      <Sidebar.Trigger class="-ml-1" />
      <Separator orientation="vertical" class="mr-2 !h-4" />
      <Breadcrumb.Root class="min-w-0 flex-1 overflow-hidden">
        <Breadcrumb.List class="flex-nowrap overflow-hidden">
          {#each breadcrumb.items as item, i (i)}
            {@const collapseOnNarrow =
              breadcrumb.items.length > 2 && i > 0 && i < breadcrumb.items.length - 1}
            {#if i > 0}
              <Breadcrumb.Separator class={collapseOnNarrow ? "hidden md:list-item" : undefined} />
            {/if}
            <Breadcrumb.Item
              class="inline-flex min-w-0 items-center gap-1.5 {i === breadcrumb.items.length - 1
                ? 'flex-1'
                : 'flex-none'} {collapseOnNarrow ? 'hidden md:inline-flex' : ''}"
            >
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
                  aria-label={item.icon === "home" ? item.label : undefined}
                  class="inline-flex max-w-40 items-center truncate"
                >
                  {#if item.icon === "home"}
                    <House class="size-3.5" />
                  {:else}
                    {#if item.icon === "workflow"}
                      <Workflow class="mr-1.5 size-3.5" />
                    {:else if item.icon === "schedules"}
                      <CalendarClock class="mr-1.5 size-3.5" />
                    {:else if item.icon === "queues"}
                      <Layers class="mr-1.5 size-3.5" />
                    {:else if item.icon === "notifications"}
                      <Bell class="mr-1.5 size-3.5" />
                    {/if}
                    {item.label}
                  {/if}
                </Breadcrumb.Link>
              {:else}
                <Breadcrumb.Page
                  title={item.tooltip}
                  class="inline-flex min-w-0 items-center truncate"
                >
                  {#if item.icon === "home"}
                    <House class="size-3.5" />
                  {:else}
                    {#if item.icon === "workflow"}
                      <Workflow class="mr-1.5 size-3.5" />
                    {:else if item.icon === "schedules"}
                      <CalendarClock class="mr-1.5 size-3.5" />
                    {:else if item.icon === "queues"}
                      <Layers class="mr-1.5 size-3.5" />
                    {:else if item.icon === "notifications"}
                      <Bell class="mr-1.5 size-3.5" />
                    {/if}
                    {item.label}
                  {/if}
                </Breadcrumb.Page>
              {/if}
            </Breadcrumb.Item>
          {/each}
        </Breadcrumb.List>
      </Breadcrumb.Root>
      <div class="ml-auto flex flex-none items-center gap-1">
        <GithubLink />
        <Separator orientation="vertical" class="mx-1 !h-4" />
        <Button
          variant="ghost"
          size="icon-sm"
          onclick={toggleTheme}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {#if isDark}
            <Sun />
          {:else}
            <Moon />
          {/if}
        </Button>
      </div>
    </header>
    <div class="flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto">
      {@render children()}
    </div>
  </Sidebar.Inset>
</Sidebar.Provider>
