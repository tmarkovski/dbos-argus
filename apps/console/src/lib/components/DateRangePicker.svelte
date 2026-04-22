<script lang="ts">
  import { Popover, RangeCalendar } from "bits-ui";
  import {
    CalendarDate,
    getLocalTimeZone,
    today,
    type DateValue,
  } from "@internationalized/date";

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
  <Popover.Trigger
    class="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-xs hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-400 data-[state=open]:bg-neutral-50"
  >
    <svg
      class="h-4 w-4 text-neutral-500"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        stroke-width="2"
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
      />
    </svg>
    <span class="{isEmpty ? 'text-neutral-400' : 'text-neutral-800'}">{display}</span>
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content
      sideOffset={6}
      class="z-20 rounded-lg border border-neutral-200 bg-white p-3 shadow-lg outline-none"
    >
      <RangeCalendar.Root
        bind:value
        weekdayFormat="short"
        class="select-none"
      >
        {#snippet children({ months, weekdays })}
          <RangeCalendar.Header class="mb-2 flex items-center justify-between">
            <RangeCalendar.PrevButton
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-neutral-600 hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-neutral-400"
              aria-label="Previous month"
            >
              ‹
            </RangeCalendar.PrevButton>
            <RangeCalendar.Heading class="text-sm font-medium text-neutral-800" />
            <RangeCalendar.NextButton
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-neutral-600 hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-neutral-400"
              aria-label="Next month"
            >
              ›
            </RangeCalendar.NextButton>
          </RangeCalendar.Header>
          {#each months as month (month.value)}
            <RangeCalendar.Grid class="w-full border-collapse">
              <RangeCalendar.GridHead>
                <RangeCalendar.GridRow class="flex">
                  {#each weekdays as weekday (weekday)}
                    <RangeCalendar.HeadCell
                      class="w-8 text-center text-[11px] font-medium uppercase tracking-wide text-neutral-400"
                    >
                      {weekday.slice(0, 2)}
                    </RangeCalendar.HeadCell>
                  {/each}
                </RangeCalendar.GridRow>
              </RangeCalendar.GridHead>
              <RangeCalendar.GridBody>
                {#each month.weeks as weekDates (weekDates[0].toString())}
                  <RangeCalendar.GridRow class="mt-1 flex w-full">
                    {#each weekDates as date (date.toString())}
                      <RangeCalendar.Cell
                        {date}
                        month={month.value}
                        class="relative p-0 text-center text-sm data-[range-middle]:bg-blue-50 data-[selection-end]:rounded-r-md data-[selection-start]:rounded-l-md first:data-[range-middle]:rounded-l-md last:data-[range-middle]:rounded-r-md"
                      >
                        <RangeCalendar.Day
                          class="inline-flex h-8 w-8 items-center justify-center rounded-md text-neutral-700 hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-neutral-400 data-[disabled]:text-neutral-300 data-[disabled]:hover:bg-transparent data-[outside-month]:text-neutral-300 data-[outside-visible-months]:opacity-0 data-[outside-visible-months]:pointer-events-none data-[selected]:bg-neutral-900 data-[selected]:text-white data-[selected]:hover:bg-neutral-900 data-[today]:ring-1 data-[today]:ring-neutral-400 data-[unavailable]:line-through data-[unavailable]:text-neutral-300"
                        />
                      </RangeCalendar.Cell>
                    {/each}
                  </RangeCalendar.GridRow>
                {/each}
              </RangeCalendar.GridBody>
            </RangeCalendar.Grid>
          {/each}
        {/snippet}
      </RangeCalendar.Root>
      <div class="mt-3 flex items-center justify-between border-t border-neutral-200 pt-2">
        <button
          type="button"
          onclick={clear}
          class="rounded-md px-2 py-1 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
        >
          Clear
        </button>
        <Popover.Close
          class="rounded-md bg-neutral-900 px-3 py-1 text-xs font-medium text-white hover:bg-neutral-800"
        >
          Done
        </Popover.Close>
      </div>
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
