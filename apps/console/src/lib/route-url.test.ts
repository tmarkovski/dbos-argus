import { describe, expect, it } from "vitest";

import { routeUrl } from "./route-url";

describe("routeUrl", () => {
  it("extracts the route from the fragment at the root mount", () => {
    const u = routeUrl(new URL("http://h/#/workflows/abc/"));
    expect(u.pathname).toBe("/workflows/abc/");
  });

  it("extracts the route behind a reverse-proxy mount prefix", () => {
    const u = routeUrl(new URL("http://h/argus/#/workflows/abc/"));
    expect(u.pathname).toBe("/workflows/abc/");
  });

  it("surfaces query params carried inside the fragment", () => {
    const u = routeUrl(new URL("http://h/argus/#/workflows/?queue_name=q1&view=timeline"));
    expect(u.pathname).toBe("/workflows/");
    expect(u.searchParams.get("queue_name")).toBe("q1");
    expect(u.searchParams.get("view")).toBe("timeline");
  });

  it("treats a missing fragment as the root route regardless of mount", () => {
    expect(routeUrl(new URL("http://h/")).pathname).toBe("/");
    expect(routeUrl(new URL("http://h/argus/")).pathname).toBe("/");
  });

  it("treats a plain in-page anchor as the root route", () => {
    expect(routeUrl(new URL("http://h/argus/#section")).pathname).toBe("/");
  });
});
