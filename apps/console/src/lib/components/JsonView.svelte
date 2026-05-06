<script lang="ts">
  // Lightweight, dependency-free JSON syntax highlighter. Tries to parse the
  // input as JSON; if it parses, runs the regex tokenizer and renders the
  // result via {@html}. If it doesn't parse (raw base64, malformed strings),
  // falls back to escaped plain text so the box still shows the value.
  let { text, class: className = "" }: { text: string; class?: string } = $props();

  function escape(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Crockford's classic JSON tokenizer regex: strings (with optional trailing
  // colon to detect keys), booleans, null, numbers. Runs over already-escaped
  // text so any literal `<` inside a string is harmless.
  const TOKEN =
    /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(?:\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

  function highlight(json: string): string {
    return escape(json).replace(TOKEN, (match) => {
      let cls = "tk-num";
      if (match.charCodeAt(0) === 34 /* " */) {
        cls = /:\s*$/.test(match) ? "tk-key" : "tk-str";
      } else if (match === "true" || match === "false") {
        cls = "tk-bool";
      } else if (match === "null") {
        cls = "tk-null";
      }
      return `<span class="${cls}">${match}</span>`;
    });
  }

  const rendered = $derived.by(() => {
    try {
      JSON.parse(text);
      return highlight(text);
    } catch {
      return escape(text);
    }
  });
</script>

<pre class="json-view {className}">{@html rendered}</pre>

<style>
  .json-view :global(.tk-key) {
    color: var(--primary);
  }
  .json-view :global(.tk-str) {
    color: var(--status-success);
  }
  .json-view :global(.tk-num) {
    color: var(--status-warning);
  }
  .json-view :global(.tk-bool) {
    color: var(--status-running);
  }
  .json-view :global(.tk-null) {
    color: var(--muted-foreground);
    font-style: italic;
  }
</style>
