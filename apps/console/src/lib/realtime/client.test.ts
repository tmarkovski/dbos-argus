import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RealtimeClient } from "./client.svelte";
import type { ClientMessage, ServerMessage } from "./protocol";

/**
 * Minimal WebSocket fake. Tests drive the lifecycle manually via
 * `triggerOpen`, `deliver`, and `triggerClose`. The class records every
 * outbound message in `sent` for assertions.
 */
class FakeWebSocket {
  static OPEN = 1;
  static CLOSED = 3;

  readyState: number = 0; // CONNECTING
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  sent: ClientMessage[] = [];

  constructor(public url: string) {}

  send(payload: string): void {
    this.sent.push(JSON.parse(payload) as ClientMessage);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    // Use plain Event — `CloseEvent` isn't a globally-defined constructor
    // under vitest's node environment in every Node version, and our
    // handler doesn't read the event anyway.
    this.onclose?.(new Event("close") as CloseEvent);
  }

  triggerOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  deliver(msg: ServerMessage): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(msg) }));
  }
}

// Shadow the real WebSocket constants on the fake so the client's
// `socket.readyState !== WebSocket.OPEN` check works under vitest's node
// environment (where `WebSocket` is undefined unless we polyfill it).
beforeEach(() => {
  // @ts-expect-error - polyfill global for node test env
  globalThis.WebSocket = FakeWebSocket;
});

afterEach(() => {
  // @ts-expect-error - clean up polyfill
  delete globalThis.WebSocket;
});

function makeClient(): { client: RealtimeClient; sockets: FakeWebSocket[] } {
  const sockets: FakeWebSocket[] = [];
  const client = new RealtimeClient({
    url: "ws://test/ws",
    socketFactory: (url) => {
      const ws = new FakeWebSocket(url);
      sockets.push(ws);
      return ws as unknown as WebSocket;
    },
    heartbeatMs: 1_000_000, // disable heartbeat for most tests
    initialBackoffMs: 5,
    maxBackoffMs: 5,
  });
  return { client, sockets };
}

describe("RealtimeClient", () => {
  it("opens a socket and sends subscribe on first subscribe()", () => {
    const { client, sockets } = makeClient();
    const onSnapshot = vi.fn();
    const onUpdate = vi.fn();

    client.subscribe("stats", undefined, { onSnapshot, onUpdate });
    expect(sockets).toHaveLength(1);
    const ws = sockets[0];

    ws.triggerOpen();
    expect(ws.sent).toHaveLength(1);
    expect(ws.sent[0]).toMatchObject({ type: "subscribe", channel: "stats" });

    client.close();
  });

  it("delivers snapshot then update to the right handler", () => {
    const { client, sockets } = makeClient();
    const handlers = { onSnapshot: vi.fn(), onUpdate: vi.fn() };

    client.subscribe("stats", undefined, handlers);
    const ws = sockets[0];
    ws.triggerOpen();

    const subId = (ws.sent[0] as { sub_id: string }).sub_id;
    ws.deliver({ type: "ack", sub_id: subId, op: "subscribe" });
    ws.deliver({ type: "snapshot", sub_id: subId, channel: "stats", data: { total: 1 } });
    ws.deliver({ type: "update", sub_id: subId, channel: "stats", data: { total: 2 } });

    expect(handlers.onSnapshot).toHaveBeenCalledTimes(1);
    expect(handlers.onSnapshot).toHaveBeenCalledWith({ total: 1 }, expect.any(Object));
    expect(handlers.onUpdate).toHaveBeenCalledTimes(1);
    expect(handlers.onUpdate).toHaveBeenCalledWith({ total: 2 }, expect.any(Object));

    client.close();
  });

  it("queues subscribe when called before socket opens, then flushes on open", () => {
    const { client, sockets } = makeClient();
    client.subscribe("stats", undefined, { onSnapshot: vi.fn(), onUpdate: vi.fn() });
    const ws = sockets[0];

    expect(ws.sent).toHaveLength(0); // socket not open yet
    ws.triggerOpen();
    expect(ws.sent).toHaveLength(1);
    expect(ws.sent[0].type).toBe("subscribe");

    client.close();
  });

  it("replays subscriptions on reconnect", async () => {
    const { client, sockets } = makeClient();
    client.subscribe("stats", undefined, { onSnapshot: vi.fn(), onUpdate: vi.fn() });
    client.subscribe("workflows", { limit: 50 }, { onSnapshot: vi.fn(), onUpdate: vi.fn() });

    const ws1 = sockets[0];
    ws1.triggerOpen();
    expect(ws1.sent).toHaveLength(2);

    // Simulate the socket dropping. Backoff is 5ms so a small wait is
    // enough for the client to schedule + execute the reconnect.
    ws1.close();
    // Wait long enough for the reconnect setTimeout to fire (5ms) plus
    // jitter (±20%). 200ms is plenty.
    await new Promise((r) => setTimeout(r, 200));

    expect(sockets).toHaveLength(2);
    const ws2 = sockets[1];
    ws2.triggerOpen();
    expect(ws2.sent).toHaveLength(2);
    expect(ws2.sent.map((m) => (m as { channel?: string }).channel).sort()).toEqual([
      "stats",
      "workflows",
    ]);

    client.close();
  });

  it("dispose() removes the subscription server-side and stops snapshots", () => {
    const { client, sockets } = makeClient();
    const handlers = { onSnapshot: vi.fn(), onUpdate: vi.fn() };
    const sub = client.subscribe("stats", undefined, handlers);

    const ws = sockets[0];
    ws.triggerOpen();
    const subId = (ws.sent[0] as { sub_id: string }).sub_id;
    ws.deliver({ type: "snapshot", sub_id: subId, channel: "stats", data: { total: 1 } });
    expect(handlers.onSnapshot).toHaveBeenCalledTimes(1);

    sub.dispose();
    const lastMsg = ws.sent.at(-1);
    expect(lastMsg?.type).toBe("unsubscribe");

    // Even if the server (mistakenly) keeps sending updates, the client
    // shouldn't dispatch them to the disposed handler.
    handlers.onSnapshot.mockClear();
    handlers.onUpdate.mockClear();
    ws.deliver({ type: "update", sub_id: subId, channel: "stats", data: { total: 2 } });
    expect(handlers.onSnapshot).not.toHaveBeenCalled();
    expect(handlers.onUpdate).not.toHaveBeenCalled();

    client.close();
  });

  it("updateParams sends update_params over the open socket", () => {
    const { client, sockets } = makeClient();
    const sub = client.subscribe(
      "workflow",
      { id: "a" },
      { onSnapshot: vi.fn(), onUpdate: vi.fn() },
    );
    const ws = sockets[0];
    ws.triggerOpen();
    ws.sent.length = 0;

    sub.updateParams({ id: "b" });
    expect(ws.sent).toHaveLength(1);
    expect(ws.sent[0]).toMatchObject({ type: "update_params", params: { id: "b" } });

    client.close();
  });

  it("routes channel errors to the subscription's onError", () => {
    const { client, sockets } = makeClient();
    const onError = vi.fn();
    client.subscribe("stats", undefined, {
      onSnapshot: vi.fn(),
      onUpdate: vi.fn(),
      onError,
    });
    const ws = sockets[0];
    ws.triggerOpen();
    const subId = (ws.sent[0] as { sub_id: string }).sub_id;

    ws.deliver({ type: "error", sub_id: subId, code: "snapshot_failed", message: "DB down" });
    expect(onError).toHaveBeenCalledWith("snapshot_failed", "DB down");

    client.close();
  });

  it("closes the socket when the last subscription is disposed", () => {
    const { client, sockets } = makeClient();
    const sub = client.subscribe("stats", undefined, { onSnapshot: vi.fn(), onUpdate: vi.fn() });
    const ws = sockets[0];
    ws.triggerOpen();
    expect(ws.readyState).toBe(FakeWebSocket.OPEN);

    sub.dispose();
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED);

    client.close();
  });

  it("connectionStatus reflects the socket lifecycle", async () => {
    const { client, sockets } = makeClient();
    expect(client.connectionStatus).toBe("closed");

    client.subscribe("stats", undefined, { onSnapshot: vi.fn(), onUpdate: vi.fn() });
    expect(client.connectionStatus).toBe("connecting");

    sockets[0].triggerOpen();
    expect(client.connectionStatus).toBe("open");

    sockets[0].close();
    // After close + reconnect attempt, status drops to "connecting" again.
    await new Promise((r) => setTimeout(r, 1));
    expect(["connecting", "closed"]).toContain(client.connectionStatus);

    client.close();
    expect(client.connectionStatus).toBe("closed");
  });
});
