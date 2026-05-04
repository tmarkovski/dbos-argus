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
      if (this.health.database === "up" && !this.diagnostics && !this.diagnosticsLoading) {
        // First-paint fetch only — the recovery loop in `connInterval` below
        // handles re-polling when the schema starts missing and later
        // materializes (e.g. a fresh DB that a DBOS app connects to mid-
        // session). The health channel dedupes identical snapshots, so we
        // can't rely on update frames as the recovery trigger.
        void this.refreshDiagnostics();
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
    // Two responsibilities folded into one ticker:
    // 1. Surface persistent WS disconnects as `fetchError` so the indicator
    //    turns red. Polled rather than effect-driven because the realtime
    //    client's `connectionStatus` is a `$state` only meaningful inside
    //    Svelte reactivity contexts.
    // 2. Re-poll `/api/sql-diagnostics` on a 5s cadence while the last
    //    result reported issues — the health channel dedupes identical
    //    snapshots, so we can't piggyback the recovery on update frames.
    let diagTickCounter = 0;
    this.connInterval = setInterval(() => {
      const status = realtimeClient.connectionStatus;
      if (status !== "open") {
        if (!this.health) {
          this.fetchError = realtimeClient.lastError ?? "websocket disconnected";
        }
        return;
      }
      // Snapshot will follow shortly; `onSnapshot` clears any prior error.
      // While issues are reported, retry every 5 ticks (≈5s) — this is the
      // "DBOS app just connected, schema is now there" recovery path.
      diagTickCounter += 1;
      if (
        diagTickCounter % 5 === 0
        && this.diagnostics
        && !this.diagnostics.ok
        && this.health?.database === "up"
        && !this.diagnosticsLoading
      ) {
        void this.refreshDiagnostics();
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
    await this.refreshDiagnostics();
  }

  // Force a re-fetch even when `diagnostics` is already populated. Used by
  // the health-update path to converge the schema indicator after the dbos.*
  // tables come into existence on a previously-empty DB.
  async refreshDiagnostics(): Promise<void> {
    if (this.health?.database !== "up" || this.diagnosticsLoading) return;
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
