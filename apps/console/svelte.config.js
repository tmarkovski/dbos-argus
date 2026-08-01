import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: "build",
      assets: "build",
      // With hash routing the shell is prerendered to index.html with
      // *relative* asset paths — that is what makes the bundle work behind a
      // reverse-proxy prefix. Naming the fallback anything else keeps the
      // adapter from overwriting it with the absolute-path fallback page
      // (the server's own catch-all serves index.html for unknown paths).
      fallback: "404.html",
      precompress: false,
      strict: true,
    }),
    // Hash routing makes the built console mount-point agnostic: assets are
    // referenced relatively and routes live in the fragment, so the same
    // bundle works served at / or behind a reverse-proxy prefix (e.g. /argus)
    // with no build-time base path. API/WS calls are relative for the same
    // reason. Internal links must use the "#/..." form.
    router: { type: "hash" },
  },
};

export default config;
