import type { Health, SqlDiagnostics } from "$lib/connection-diagnostics";
import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

class ConnectionState {
  health = $state<Health | null>(null);
  // `fetchError` historically meant "we failed to fetch /healthz". Under the
  // realtime layer it represents either a failed snapshot from the server-side
  // health channel OR a closed/connecting websocket — the consumer-visible
  // condition is the same: "we don't have a current health reading".
  fetchError = $state<string | null>(null);
  diagnostics = $state<SqlDiagnostics | null>(null);
  diagnosticsLoading = $state(false);
  diagnosticsError = $state<string | null>(null);
  sheetOpen = $state(false);

  private handle: SubscriptionHandle | null = null;
  private refs = 0;
  private connInterval: ReturnType<typeof setInterval> | null = null;

  start(): void {
    this.refs += 1;
    if (this.handle) return;
    const apply = (data: unknown) => {
      this.health = data as Health;
      this.fetchError = null;
      // Auto-fetch SQL diagnostics on the first up-health snapshot. The
      // original code did this in the layout's onMount after the awaited
      // refreshHealth(); preserving that here keeps the indicator turning
      // yellow on schema drift without extra wiring at every callsite.
      if (this.health.database === "up" && !this.diagnostics && !this.diagnosticsLoading) {
        void this.ensureDiagnostics();
      }
    };
    this.handle = realtimeClient.subscribe("health", undefined, {
      onSnapshot: apply,
      onUpdate: apply,
      onError: (_code, message) => {
        // Preserve the prior contract: any data-fetch failure surfaces as
        // `fetchError`, and the indicator falls back to "disconnected".
        this.fetchError = message;
      },
    });
    // Surface persistent disconnects as fetchError so the connection
    // indicator turns red. Polled rather than effect-driven because the
    // realtime client's `connectionStatus` is a `$state` only meaningful
    // inside Svelte reactivity contexts; this loop is portable.
    this.connInterval = setInterval(() => {
      const status = realtimeClient.connectionStatus;
      if (status === "open") {
        // Snapshot will follow shortly; `onSnapshot` clears the error.
        return;
      }
      // We've been closed/connecting AND we have no recent health — surface
      // as a fetch error. Once a snapshot lands, onSnapshot clears this.
      if (!this.health) {
        this.fetchError = realtimeClient.lastError ?? "websocket disconnected";
      }
    }, 1000);
  }

  stop(): void {
    if (this.refs > 0) this.refs -= 1;
    if (this.refs > 0) return;
    this.handle?.dispose();
    this.handle = null;
    if (this.connInterval) clearInterval(this.connInterval);
    this.connInterval = null;
  }

  async ensureDiagnostics(): Promise<void> {
    if (this.health?.database !== "up" || this.diagnosticsLoading || this.diagnostics) return;

    this.diagnosticsError = null;
    this.diagnosticsLoading = true;
    try {
      const res = await fetch("/api/sql-diagnostics");
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // The endpoint normally returns JSON; fall back to the status text if it doesn't.
        }
        throw new Error(detail);
      }

      this.diagnostics = (await res.json()) as SqlDiagnostics;
    } catch (e) {
      this.diagnosticsError = e instanceof Error ? e.message : String(e);
    } finally {
      this.diagnosticsLoading = false;
    }
  }

  open() {
    this.sheetOpen = true;
  }
}

export const connectionState = new ConnectionState();
