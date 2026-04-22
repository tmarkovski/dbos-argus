<script lang="ts">
  import type { QueueTableProps } from "./types.js";

  let { queues }: QueueTableProps = $props();
</script>

<table class="argus-queue-table" data-testid="queue-table">
  <thead>
    <tr>
      <th>Queue</th>
      <th>Pending</th>
      <th>Running</th>
      <th>Failed</th>
    </tr>
  </thead>
  <tbody>
    {#each queues as q (q.id)}
      <tr>
        <td>{q.name}</td>
        <td>{q.pending}</td>
        <td>{q.running}</td>
        <td>{q.failed}</td>
      </tr>
    {/each}
  </tbody>
</table>
