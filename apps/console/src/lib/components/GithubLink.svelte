<script lang="ts">
  import { onMount } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";

  const REPO = "tmarkovski/dbos-argus";
  const HREF = `https://github.com/${REPO}`;
  const CACHE_KEY = "argus.github.stars";

  let stars = $state<number | null>(null);

  function format(n: number): string {
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  onMount(() => {
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached !== null) stars = Number(cached);
    } catch {
      // sessionStorage may be unavailable (private mode, sandboxed iframe).
    }
    fetch(`https://api.github.com/repos/${REPO}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && typeof data.stargazers_count === "number") {
          stars = data.stargazers_count;
          try {
            sessionStorage.setItem(CACHE_KEY, String(stars));
          } catch {
            // see above
          }
        }
      })
      .catch(() => {
        // Offline or GitHub rate-limited (60/hr unauth) — fall through with
        // whatever we had cached. The icon alone is still useful.
      });
  });
</script>

<Button
  variant="ghost"
  size="sm"
  href={HREF}
  target="_blank"
  rel="noopener noreferrer"
  title="View Argus on GitHub"
  aria-label="View Argus on GitHub"
  class="gap-1.5"
>
  <svg viewBox="0 0 24 24" fill="currentColor" class="size-4" aria-hidden="true">
    <path
      d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.04-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.69 1.25 3.34.95.1-.74.4-1.25.73-1.54-2.55-.29-5.23-1.27-5.23-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.46.11-3.05 0 0 .96-.31 3.15 1.17a10.9 10.9 0 0 1 5.74 0c2.19-1.48 3.15-1.17 3.15-1.17.62 1.59.23 2.76.11 3.05.73.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.65.41.36.78 1.06.78 2.14v3.17c0 .31.21.66.79.55C20.21 21.38 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"
    />
  </svg>
  {#if stars !== null}
    <span class="tabular-nums text-xs">★ {format(stars)}</span>
  {/if}
</Button>
