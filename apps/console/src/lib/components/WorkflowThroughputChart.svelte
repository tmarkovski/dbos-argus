<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { scaleUtc } from "d3-scale";
  import { Area, AreaChart } from "layerchart";
  import { curveNatural } from "d3-shape";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Chart from "$lib/components/ui/chart/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";

  type ApiBucket = {
    ts: string;
    succeeded: number;
    errored: number;
    running: number;
  };

  type Range = "24h" | "7d" | "30d";

  let range = $state<Range>("7d");
  let data = $state<{ ts: Date; succeeded: number; errored: number; running: number }[]>([]);
  let timer: ReturnType<typeof setInterval> | undefined;

  async function refresh() {
    try {
      const r = await fetch(`/api/stats/timeseries?range=${range}`);
      if (!r.ok) return;
      const buckets: ApiBucket[] = await r.json();
      data = buckets.map((b) => ({
        ts: new Date(b.ts),
        succeeded: b.succeeded,
        errored: b.errored,
        running: b.running,
      }));
    } catch {
      // silently ignore — the dashboard's main fetch will surface the error
    }
  }

  $effect(() => {
    void range;
    refresh();
  });

  onMount(() => {
    timer = setInterval(refresh, 10_000);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
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
    <Chart.Container config={chartConfig} class="aspect-auto h-[250px] w-full">
      <AreaChart
        legend
        {data}
        x="ts"
        xScale={scaleUtc()}
        series={[
          { key: "succeeded", label: "Succeeded", color: chartConfig.succeeded.color },
          { key: "errored", label: "Errored", color: chartConfig.errored.color },
          { key: "running", label: "Running", color: chartConfig.running.color },
        ]}
        seriesLayout="stack"
        props={{
          xAxis: {
            ticks: range === "24h" ? 6 : range === "7d" ? 7 : undefined,
            format: xFormat,
          },
          yAxis: { format: () => "" },
        }}
      >
        {#snippet marks({ context }: { context: { series: { visibleSeries: { key: string }[] } } })}
          <defs>
            <linearGradient id="fillSucceeded" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stop-color="var(--color-succeeded)" stop-opacity={0.9} />
              <stop offset="95%" stop-color="var(--color-succeeded)" stop-opacity={0.1} />
            </linearGradient>
            <linearGradient id="fillErrored" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stop-color="var(--color-errored)" stop-opacity={0.9} />
              <stop offset="95%" stop-color="var(--color-errored)" stop-opacity={0.1} />
            </linearGradient>
            <linearGradient id="fillRunning" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stop-color="var(--color-running)" stop-opacity={0.9} />
              <stop offset="95%" stop-color="var(--color-running)" stop-opacity={0.1} />
            </linearGradient>
          </defs>
          {#each context.series.visibleSeries as s (s.key)}
            <Area
              seriesKey={s.key}
              curve={curveNatural}
              fillOpacity={0.4}
              line={{ class: "stroke-1" }}
              motion="tween"
              fill={s.key === "succeeded"
                ? "url(#fillSucceeded)"
                : s.key === "errored"
                  ? "url(#fillErrored)"
                  : "url(#fillRunning)"}
            />
          {/each}
        {/snippet}
        {#snippet tooltip()}
          <Chart.Tooltip labelFormatter={tooltipLabelFormat} indicator="line" />
        {/snippet}
      </AreaChart>
    </Chart.Container>
  </Card.Content>
</Card.Root>
