/**
 * Under the hash router, `page.url` is the *browser* URL: the route and its
 * query live in the fragment, and the pathname is wherever the console
 * happens to be mounted (`/`, `/argus/`, ...). Normalize to a URL whose
 * pathname and searchParams are the route's own — use this instead of
 * reading `page.url.pathname` / `page.url.searchParams` directly.
 */
export function routeUrl(pageUrl: URL): URL {
  const hash = pageUrl.hash;
  return new URL(hash.startsWith("#/") ? hash.slice(1) : "/", pageUrl.origin);
}
