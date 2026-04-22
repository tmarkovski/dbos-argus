<script lang="ts">
  import type { StatusPillProps } from "./types.js";

  let { status, label }: StatusPillProps = $props();
</script>

<span class="argus-status-pill argus-status-{status}" data-testid="status-pill">
  {label ?? status}
</span>
