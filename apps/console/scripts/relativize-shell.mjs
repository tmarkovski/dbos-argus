// Make the built shell mount-point agnostic.
//
// With hash routing, SvelteKit already computes the runtime `base` from
// `location`, but the prerendered index.html still emits the entry imports,
// modulepreload links, and favicon hrefs as root-absolute URLs ("/_app/...").
// Served behind a stripped reverse-proxy prefix those resolve outside the
// mount and 404. The document URL is always the mount root in hash mode, so
// plain relative URLs are correct everywhere — at "/" and behind any prefix.
//
// 404.html (the adapter fallback) is left untouched: the Argus server's SPA
// catch-all serves index.html itself, and a fallback served at an unknown
// depth is exactly the case relative URLs cannot handle.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const path = fileURLToPath(new URL("../build/index.html", import.meta.url));
const html = readFileSync(path, "utf8");
const out = html.replaceAll('href="/', 'href="./').replaceAll('import("/', 'import("./');
writeFileSync(path, out);
console.log("relativized build/index.html");
