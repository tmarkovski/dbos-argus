export type Health = {
  status: string;
  database: string;
  database_url?: string;
  database_error?: string;
  database_dialect?: "postgres" | "sqlite";
  database_version?: string;
  dbos_schema_revision?: string;
};

export function formatDialectLabel(
  dialect: Health["database_dialect"],
  version?: string,
): string {
  const name = dialect === "sqlite" ? "SQLite" : dialect === "postgres" ? "PostgreSQL" : null;
  if (!name) return "DBOS database";
  return version ? `${name} ${version}` : name;
}

export type SqlDiagnosticIssueKind = "missing_table" | "missing_column" | "wrong_type";

export type SqlDiagnosticIssue = {
  kind: SqlDiagnosticIssueKind;
  table_name: string;
  column_name: string | null;
  expected_type: string | null;
  actual_type: string | null;
  detail: string;
};

/**
 * DBOS schema-revision grading, from `dbos.dbos_migrations.version`.
 *
 * `compatible` is false only when the revision is known *and* below what this
 * Argus build needs. A null `revision` (no migrations table: fresh DB, or a
 * legacy Alembic-managed one) makes no claim and stays compatible — `issues` is
 * the authority there.
 */
export type DbosCompat = {
  dialect: "postgres" | "sqlite";
  revision: number | null;
  required_revision: number;
  compatible: boolean;
  recommended_argus_version: string | null;
  recommended_dbos_version: string | null;
  missing_columns: string[];
  message: string | null;
};

export type SqlDiagnostics = {
  ok: boolean;
  issues: SqlDiagnosticIssue[];
  compat?: DbosCompat;
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
  // A stale revision normally shows up as missing columns too, but grade it
  // explicitly so the indicator can't read green on a DB we've already judged
  // too old.
  if (diagnostics && (!diagnostics.ok || diagnostics.compat?.compatible === false)) {
    return "issues";
  }
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
  if (!diagnostics) return null;
  // The revision verdict outranks the column count: it's the same underlying
  // problem stated in the form the user can act on.
  const outdated = dbosCompatOutdated(diagnostics);
  if (outdated) {
    return `DBOS schema revision ${outdated.revision} — Argus needs ${outdated.required_revision}`;
  }
  if (diagnostics.ok) return null;
  const count = diagnostics.issues.length;
  return `${count} schema issue${count === 1 ? "" : "s"} found`;
}

/**
 * The compat report, but only when it's a definite "your DB is too old" verdict
 * with a known revision. Returns null when compatible, absent, or ungraded, so
 * callers can treat a truthy result as "render the pin advice".
 */
export function dbosCompatOutdated(
  diagnostics: SqlDiagnostics | null,
): (DbosCompat & { revision: number }) | null {
  const compat = diagnostics?.compat;
  if (!compat || compat.compatible || compat.revision === null) return null;
  return compat as DbosCompat & { revision: number };
}

/** `pip install 'dbos-argus==0.0.28'`, or null when there's nothing to pin. */
export function argusPinCommand(compat: DbosCompat | null): string | null {
  if (!compat?.recommended_argus_version) return null;
  return `pip install 'dbos-argus==${compat.recommended_argus_version}'`;
}
