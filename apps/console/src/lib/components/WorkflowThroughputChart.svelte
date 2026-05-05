<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { BarChart } from "layerchart";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Chart from "$lib/components/ui/chart/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

  type ApiBucket = {
    ts: string;
    succeeded: number;
    errored: number;
    running: number;
  };

  type Range = "24h" | "7d" | "30d";

  const RANGE_STORAGE_KEY = "argus.dashboard.throughput.range";

  function loadRange(): Range {
    if (typeof localStorage === "undefined") return "7d";
    const v = localStorage.getItem(RANGE_STORAGE_KEY);
    return v === "24h" || v === "7d" || v === "30d" ? v : "7d";
  }

  let range = $state<Range>(loadRange());
  let data = $state<{ ts: Date; succeeded: number; errored: number; running: number }[]>([]);
  let handle: SubscriptionHandle | null = null;

  function applySnapshot(payload: unknown): void {
    if (!Array.isArray(payload)) return;
    data = (payload as ApiBucket[]).map((b) => ({
      ts: new Date(b.ts),
      succeeded: b.succeeded,
      errored: b.errored,
      running: b.running,
    }));
  }

  // Persist range + push update_params on change so the same subscription
  // re-keys server-side instead of unsubscribing + resubscribing.
  $effect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(RANGE_STORAGE_KEY, range);
    }
    handle?.updateParams({ range });
  });

  onMount(() => {
    handle = realtimeClient.subscribe(
      "stats.timeseries",
      { range },
      {
        onSnapshot: applySnapshot,
        onUpdate: applySnapshot,
        // Errors are intentionally silent — the dashboard's main connection
        // indicator already surfaces server-side problems.
      },
    );
  });

  onDestroy(() => {
    handle?.dispose();
  });

  const rangeLabel = $derived.by(() => {
    if (range === "24h") return "Last 24 hours";
    if (range === "30d") return "Last 30 days";
    return "Last 7 days";
  });

  const xFormat = $derived.by(() => {
    if (range === "24h") {
      return (v: Date) =>
        v.toLocaleTimeString("en-US", { hour: "numeric" });
    }
    return (v: Date) =>
      v.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  });

  const tooltipLabelFormat = $derived.by(() => {
    if (range === "24h") {
      return (v: Date) =>
        v.toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "numeric",
        });
    }
    return (v: Date) =>
      v.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  });

  const chartConfig = {
    succeeded: { label: "Succeeded", color: "#22c55e" },
    errored: { label: "Errored", color: "#ef4444" },
    running: { label: "Running", color: "#3b82f6" },
  } satisfies Chart.ChartConfig;
</script>

<Card.Root class="@container/card gap-0 py-0 shadow-xs">
  <Card.Header class="border-b py-4">
    <Card.Title class="text-base font-semibold">Workflow throughput</Card.Title>
    <Card.Description>
      <span class="hidden @[540px]/card:block">
        Workflows created over {rangeLabel.toLowerCase()}, by terminal status.
      </span>
      <span class="@[540px]/card:hidden">{rangeLabel}</span>
    </Card.Description>
    <Card.Action>
      <ToggleGroup.Root
        type="single"
        bind:value={range as string}
        variant="outline"
        class="hidden *:data-[slot=toggle-group-item]:!px-4 @[640px]/card:flex"
      >
        <ToggleGroup.Item value="24h">24h</ToggleGroup.Item>
        <ToggleGroup.Item value="7d">7 days</ToggleGroup.Item>
        <ToggleGroup.Item value="30d">30 days</ToggleGroup.Item>
      </ToggleGroup.Root>
      <Select.Root type="single" bind:value={range as string}>
        <Select.Trigger
          size="sm"
          class="flex w-32 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate @[640px]/card:hidden"
          aria-label="Select range"
        >
          <span data-slot="select-value">{rangeLabel}</span>
        </Select.Trigger>
        <Select.Content class="rounded-xl">
          <Select.Item value="24h" class="rounded-lg">Last 24 hours</Select.Item>
          <Select.Item value="7d" class="rounded-lg">Last 7 days</Select.Item>
          <Select.Item value="30d" class="rounded-lg">Last 30 days</Select.Item>
        </Select.Content>
      </Select.Root>
    </Card.Action>
  </Card.Header>
  <Card.Content class="px-2 pt-4 sm:px-6 sm:pt-6">
    <Chart.Container
      config={chartConfig}
      class="aspect-auto h-[250px] w-full [&_.lc-legend-container]:pb-2"
    >
      <BarChart
        legend
        {data}
        x="ts"
        series={[
          { key: "succeeded", label: "Succeeded", color: chartConfig.succeeded.color },
          { key: "errored", label: "Errored", color: chartConfig.errored.color },
          { key: "running", label: "Running", color: chartConfig.running.color },
        ]}
        seriesLayout="stack"
        props={{
          xAxis: {
            ticks: range === "24h" ? 6 : range === "7d" ? 7 : 6,
            format: xFormat,
          },
          yAxis: { format: () => "" },
          bars: { strokeWidth: 0 },
        }}
      >
        {#snippet tooltip()}
          <Chart.Tooltip labelFormatter={tooltipLabelFormat} indicator="dashed" />
        {/snippet}
      </BarChart>
    </Chart.Container>
  </Card.Content>
</Card.Root>
