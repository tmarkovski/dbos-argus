import { describe, expect, it } from "vitest";
import { consoleMarker } from "./index.js";

describe("console lib", () => {
  it("exports a marker string", () => {
    expect(consoleMarker).toBe("dbos-argus/console");
  });
});
