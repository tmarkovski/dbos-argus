/**
 * `createSubscription<T>(channel, params)` — typed reactive wrapper around
 * `RealtimeClient.subscribe`.
 *
 * Returns a $state-backed object that components can read from directly:
 *
 *   const stats = createSubscription<Stats>("stats");
 *   $effect(() => () => stats.dispose()); // cleanup on unmount
 *   // template: {stats.data?.total ?? "—"}
 */

import { realtimeClient, type RealtimeClient } from "./client.svelte";

export type Subscription<T> = {
  /** Latest server payload, or `null` until the first snapshot lands. */
  data: T | null;
  /** Channel-level error from the server, or null if none. */
  error: string | null;
  /** True once at least one snapshot has been delivered. */
  ready: boolean;
  /** Re-key the subscription. The next snapshot will reflect the new params. */
  updateParams: (params: Record<string, unknown> | undefined) => void;
  /** Drop the subscription. Idempotent. */
  dispose: () => void;
};

export type SubscriptionOptions = {
  /** Override the singleton client — primarily for tests. */
  client?: RealtimeClient;
};

export function createSubscription<T = unknown>(
  channel: string,
  params: Record<string, unknown> | undefined = undefined,
  options: SubscriptionOptions = {},
): Subscription<T> {
  const client = options.client ?? realtimeClient;

  // Mutable reactive state. Returned object methods read/write these fields
  // by capturing `state` in their closures — Svelte's `$state` proxies pick
  // up the writes regardless of how the object is structured.
  const state = $state({
    data: null as T | null,
    error: null as string | null,
    ready: false,
  });

  const handle = client.subscribe(channel, params, {
    onSnapshot: (data) => {
      state.data = data as T;
      state.error = null;
      state.ready = true;
    },
    onUpdate: (data) => {
      state.data = data as T;
      state.error = null;
    },
    onError: (_code, message) => {
      state.error = message;
    },
  });

  return {
    get data() {
      return state.data;
    },
    get error() {
      return state.error;
    },
    get ready() {
      return state.ready;
    },
    updateParams: (newParams) => handle.updateParams(newParams),
    dispose: () => handle.dispose(),
  };
}
