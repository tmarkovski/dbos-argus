/**
 * RealtimeClient — singleton-friendly WS subscription manager.
 *
 * Lazy connect: opens the socket on the first subscribe(). Reconnects with
 * jittered exponential backoff (capped at 8s) and replays every live
 * subscription on reconnect, so callers don't need to handle reconnection
 * logic themselves. Heartbeat ping/pong detects half-open sockets.
 *
 * The client is a `.svelte.ts` module so its reactive state ($state-backed
 * `connectionStatus` and `lastError`) can be consumed directly from
 * components.
 */

import type {
  ClientMessage,
  ConnectionStatus,
  ServerMessage,
  SnapshotMessage,
  UpdateMessage,
} from "./protocol";

export type SubscriptionHandlers = {
  /**
   * Called for the first payload AND for every replay snapshot delivered
   * after a reconnect or `update_params`. Treat as "fresh state — replace
   * what you had".
   */
  onSnapshot: (data: unknown, msg: SnapshotMessage) => void;
  /** Called for in-place updates between snapshots. */
  onUpdate: (data: unknown, msg: UpdateMessage) => void;
  /** Channel-level errors (server-side cursor/snapshot failures). */
  onError?: (code: string, message: string) => void;
};

export type SubscriptionHandle = {
  /** Re-key this subscription on the server without unsubscribing first. */
  updateParams: (params: Record<string, unknown> | undefined) => void;
  /** Unsubscribe and forget. Idempotent. */
  dispose: () => void;
};

type InternalSub = {
  subId: string;
  channel: string;
  params: Record<string, unknown> | undefined;
  handlers: SubscriptionHandlers;
};

export type ClientOptions = {
  /** Socket factory. Defaults to `new WebSocket(url)`. Tests inject a fake. */
  socketFactory?: (url: string) => WebSocket;
  /** Override the URL. Defaults to `${ws|wss}://${location.host}/ws`. */
  url?: string;
  /**
   * Heartbeat interval. A `ping` is sent every `heartbeatMs`; if no `pong`
   * arrives within `heartbeatTimeoutMs`, the socket is force-closed.
   */
  heartbeatMs?: number;
  heartbeatTimeoutMs?: number;
  /** Initial reconnect delay; doubles each attempt up to `maxBackoffMs`. */
  initialBackoffMs?: number;
  maxBackoffMs?: number;
};

const DEFAULTS = {
  heartbeatMs: 20_000,
  heartbeatTimeoutMs: 10_000,
  initialBackoffMs: 250,
  maxBackoffMs: 8_000,
};

export class RealtimeClient {
  // Reactive state — read these from components / .svelte.ts wrappers.
  connectionStatus = $state<ConnectionStatus>("closed");
  lastError = $state<string | null>(null);

  private readonly subs = new Map<string, InternalSub>();
  private socket: WebSocket | null = null;
  private nextId = 1;
  private backoffAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;

  private readonly opts: Required<Omit<ClientOptions, "url" | "socketFactory">> & {
    url: string;
    socketFactory: (url: string) => WebSocket;
  };

  constructor(options: ClientOptions = {}) {
    const url =
      options.url ??
      (typeof window !== "undefined"
        ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`
        : "ws://localhost/ws");
    this.opts = {
      url,
      socketFactory: options.socketFactory ?? ((u) => new WebSocket(u)),
      heartbeatMs: options.heartbeatMs ?? DEFAULTS.heartbeatMs,
      heartbeatTimeoutMs: options.heartbeatTimeoutMs ?? DEFAULTS.heartbeatTimeoutMs,
      initialBackoffMs: options.initialBackoffMs ?? DEFAULTS.initialBackoffMs,
      maxBackoffMs: options.maxBackoffMs ?? DEFAULTS.maxBackoffMs,
    };
  }

  // ---- Public API --------------------------------------------------------

  subscribe(
    channel: string,
    params: Record<string, unknown> | undefined,
    handlers: SubscriptionHandlers,
  ): SubscriptionHandle {
    if (this.disposed) {
      throw new Error("RealtimeClient: subscribe called after close()");
    }
    const subId = `s${this.nextId++}`;
    const sub: InternalSub = { subId, channel, params, handlers };
    this.subs.set(subId, sub);

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.send({ type: "subscribe", sub_id: subId, channel, params });
    } else {
      // Will be sent on `open` via `replaySubscriptions`. Make sure we've
      // started the connect dance.
      this.ensureConnected();
    }

    return {
      updateParams: (newParams) => this.updateParams(subId, newParams),
      dispose: () => this.unsubscribe(subId),
    };
  }

  /** Force-close the socket and stop reconnecting. Used in tests / cleanup. */
  close(): void {
    this.disposed = true;
    this.clearTimers();
    this.subs.clear();
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // Ignore — already closed.
      }
      this.socket = null;
    }
    this.connectionStatus = "closed";
  }

  // ---- Internals ---------------------------------------------------------

  private ensureConnected(): void {
    if (this.disposed) return;
    if (this.socket) return; // open or connecting
    this.connect();
  }

  private connect(): void {
    if (this.disposed) return;
    this.connectionStatus = "connecting";
    let socket: WebSocket;
    try {
      socket = this.opts.socketFactory(this.opts.url);
    } catch (e) {
      this.lastError = e instanceof Error ? e.message : String(e);
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => this.handleOpen();
    socket.onmessage = (ev) => this.handleMessage(ev);
    socket.onerror = () => {
      // The browser doesn't expose error details; rely on `onclose`
      // following up. Just record that something went wrong.
      this.lastError = "websocket error";
    };
    socket.onclose = () => this.handleClose();
  }

  private handleOpen(): void {
    this.connectionStatus = "open";
    this.lastError = null;
    this.backoffAttempt = 0;
    this.replaySubscriptions();
    this.startHeartbeat();
  }

  private handleClose(): void {
    this.socket = null;
    this.stopHeartbeat();
    if (this.disposed) {
      this.connectionStatus = "closed";
      return;
    }
    if (this.subs.size === 0) {
      // Nothing to keep alive for. Stay closed; `subscribe` will reconnect.
      this.connectionStatus = "closed";
      return;
    }
    this.scheduleReconnect();
  }

  private handleMessage(ev: MessageEvent): void {
    let msg: ServerMessage;
    try {
      msg = JSON.parse(typeof ev.data === "string" ? ev.data : "") as ServerMessage;
    } catch {
      this.lastError = "received non-JSON message";
      return;
    }
    if (msg.type === "pong") {
      this.clearPongTimer();
      return;
    }
    if (msg.type === "snapshot") {
      const sub = this.subs.get(msg.sub_id);
      sub?.handlers.onSnapshot(msg.data, msg);
      return;
    }
    if (msg.type === "update") {
      const sub = this.subs.get(msg.sub_id);
      sub?.handlers.onUpdate(msg.data, msg);
      return;
    }
    if (msg.type === "error") {
      if (msg.sub_id) {
        const sub = this.subs.get(msg.sub_id);
        sub?.handlers.onError?.(msg.code, msg.message);
      } else {
        this.lastError = `${msg.code}: ${msg.message}`;
      }
      return;
    }
    // ack — ignore by default; useful only for tests.
  }

  private replaySubscriptions(): void {
    for (const sub of this.subs.values()) {
      this.send({
        type: "subscribe",
        sub_id: sub.subId,
        channel: sub.channel,
        params: sub.params,
      });
    }
  }

  private updateParams(subId: string, params: Record<string, unknown> | undefined): void {
    const sub = this.subs.get(subId);
    if (!sub) return;
    sub.params = params;
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.send({ type: "update_params", sub_id: subId, params });
    }
    // If not open: the next replay (on reconnect) will use the new params,
    // because `sub.params` is the source of truth.
  }

  private unsubscribe(subId: string): void {
    if (!this.subs.has(subId)) return;
    this.subs.delete(subId);
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.send({ type: "unsubscribe", sub_id: subId });
    }
    if (this.subs.size === 0 && !this.disposed) {
      // No live subscriptions — close the socket to avoid keeping it open
      // for nothing. Next `subscribe` will reopen.
      if (this.socket) {
        try {
          this.socket.close();
        } catch {
          /* already closed */
        }
      }
    }
  }

  private send(msg: ClientMessage): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
    try {
      this.socket.send(JSON.stringify(msg));
    } catch (e) {
      this.lastError = e instanceof Error ? e.message : String(e);
    }
  }

  // ---- Heartbeat ---------------------------------------------------------

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
      this.send({ type: "ping" });
      this.pongTimer = setTimeout(() => {
        // No pong — assume the connection is half-open. Force-close, which
        // triggers the reconnect dance via `onclose`.
        try {
          this.socket?.close();
        } catch {
          /* ignore */
        }
      }, this.opts.heartbeatTimeoutMs);
    }, this.opts.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
    this.clearPongTimer();
  }

  private clearPongTimer(): void {
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.pongTimer = null;
  }

  // ---- Reconnect ---------------------------------------------------------

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer) return;
    this.connectionStatus = "connecting";
    const base = Math.min(
      this.opts.initialBackoffMs * 2 ** this.backoffAttempt,
      this.opts.maxBackoffMs,
    );
    // ±20% jitter so a fleet of clients doesn't reconnect in lockstep.
    const jitter = base * (Math.random() * 0.4 - 0.2);
    const delay = Math.max(50, Math.round(base + jitter));
    this.backoffAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.stopHeartbeat();
  }
}

// Singleton — use this from app code unless you specifically want a separate
// connection (e.g. tests).
export const realtimeClient = new RealtimeClient();
