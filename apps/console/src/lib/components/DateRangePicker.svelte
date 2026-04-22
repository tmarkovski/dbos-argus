<script lang="ts">
  import { getLocalTimeZone, type DateValue } from "@internationalized/date";
  import CalendarIcon from "@lucide/svelte/icons/calendar";
  import { Button } from "$lib/components/ui/button";
  import * as Popover from "$lib/components/ui/popover";
  import { RangeCalendar } from "$lib/components/ui/range-calendar";

  type Range = { start: DateValue | undefined; end: DateValue | undefined };

  let {
    value = $bindable<Range>({ start: undefined, end: undefined }),
    placeholder = "Pick a date range",
  }: {
    value?: Range;
    placeholder?: string;
  } = $props();

  const fmt = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  const display = $derived.by(() => {
    const tz = getLocalTimeZone();
    if (value.start && value.end) {
      return `${fmt.format(value.start.toDate(tz))} → ${fmt.format(value.end.toDate(tz))}`;
    }
    if (value.start) return `${fmt.format(value.start.toDate(tz))} → …`;
    if (value.end) return `… → ${fmt.format(value.end.toDate(tz))}`;
    return placeholder;
  });

  const isEmpty = $derived(!value.start && !value.end);

  function clear() {
    value = { start: undefined, end: undefined };
  }
</script>

<Popover.Root>
  <Popover.Trigger>
    {#snippet child({ props })}
      <Button variant="outline" {...props}>
        <CalendarIcon />
        <span class={isEmpty ? "text-muted-foreground" : undefined}>{display}</span>
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-auto p-0" align="start">
    <RangeCalendar bind:value />
    <div class="flex items-center justify-between border-t p-2">
      <Button variant="ghost" size="sm" onclick={clear}>Clear</Button>
      <Popover.Close>
        {#snippet child({ props })}
          <Button size="sm" {...props}>Done</Button>
        {/snippet}
      </Popover.Close>
    </div>
  </Popover.Content>
</Popover.Root>
