export type Health = {
  status: string;
  database: string;
  database_url?: string;
  database_error?: string;
};

export type SqlDiagnosticIssueKind = "missing_table" | "missing_column" | "wrong_type";

export type SqlDiagnosticIssue = {
  kind: SqlDiagnosticIssueKind;
  table_name: string;
  column_name: string | null;
  expected_type: string | null;
  actual_type: string | null;
  detail: string;
};

export type SqlDiagnostics = {
  ok: boolean;
  issues: SqlDiagnosticIssue[];
};

export type ConnectionIndicatorState = "connected" | "issues" | "disconnected";

export function getConnectionIndicatorState({
  fetchError,
  health,
  diagnostics,
}: {
  fetchError: string | null;
  health: Health | null;
  diagnostics: SqlDiagnostics | null;
}): ConnectionIndicatorState {
  if (fetchError || health?.database !== "up") return "disconnected";
  if (diagnostics && !diagnostics.ok) return "issues";
  return "connected";
}

export function connectionIndicatorClass(state: ConnectionIndicatorState): string {
  if (state === "connected") return "text-status-success";
  if (state === "issues") return "text-status-warning";
  return "text-status-error";
}

export function connectionIndicatorLabel(state: ConnectionIndicatorState): string {
  return state === "disconnected" ? "Disconnected" : "Connected";
}

export function diagnosticsIssueSummary(diagnostics: SqlDiagnostics | null): string | null {
  if (!diagnostics || diagnostics.ok) return null;
  const count = diagnostics.issues.length;
  return `${count} schema issue${count === 1 ? "" : "s"} found`;
}
