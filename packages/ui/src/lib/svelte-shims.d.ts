// Minimal ambient declaration so `tsc --noEmit` accepts .svelte imports in the
// stub index file. The real component types come from Svelte 5's compiler
// when the library is consumed inside a SvelteKit app.
declare module "*.svelte" {
  import type { Component } from "svelte";
  const component: Component<Record<string, unknown>>;
  export default component;
}
