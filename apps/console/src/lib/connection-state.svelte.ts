import type { Health, SqlDiagnostics } from "$lib/connection-diagnostics";

class ConnectionState {
  health = $state<Health | null>(null);
  fetchError = $state<string | null>(null);
  diagnostics = $state<SqlDiagnostics | null>(null);
  diagnosticsLoading = $state(false);
  diagnosticsError = $state<string | null>(null);
  sheetOpen = $state(false);

  async refreshHealth() {
    try {
      const res = await fetch("/healthz");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.health = (await res.json()) as Health;
      this.fetchError = null;
    } catch (e) {
      this.health = null;
      this.fetchError = e instanceof Error ? e.message : String(e);
    }
  }

  async ensureDiagnostics() {
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
