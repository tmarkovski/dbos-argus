<script lang="ts">
  import type { EventTimelineProps } from "./types.js";

  let { events }: EventTimelineProps = $props();
</script>

<ol class="argus-event-timeline" data-testid="event-timeline">
  {#each events as event (event.id)}
    <li>
      <time datetime={event.at}>{event.at}</time>
      <strong>{event.label}</strong>
      {#if event.detail}<span>{event.detail}</span>{/if}
    </li>
  {/each}
</ol>
