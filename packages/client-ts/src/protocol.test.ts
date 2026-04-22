import { describe, expect, it } from "vitest";
import type { HelloMessage } from "./protocol.js";

describe("protocol", () => {
  it("hello message shape is assignable", () => {
    const m: HelloMessage = {
      type: "hello",
      server_version: "0.0.1",
      connection_id: "abc",
      received_at: new Date().toISOString(),
    };
    expect(m.type).toBe("hello");
  });
});
