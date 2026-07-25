import { describe, expect, it } from "vitest";

import {
  argusPinCommand,
  connectionIndicatorClass,
  connectionIndicatorLabel,
  dbosCompatOutdated,
  diagnosticsIssueSummary,
  getConnectionIndicatorState,
  type DbosCompat,
  type Health,
  type SqlDiagnostics,
} from "./connection-diagnostics.js";

const connectedHealth: Health = {
  status: "ok",
  database: "up",
};

const compatibleCompat: DbosCompat = {
  dialect: "postgres",
  revision: 41,
  required_revision: 41,
  compatible: true,
  recommended_argus_version: null,
  recommended_dbos_version: null,
  missing_columns: [],
  message: null,
};

const outdatedCompat: DbosCompat = {
  dialect: "postgres",
  revision: 38,
  required_revision: 41,
  compatible: false,
  recommended_argus_version: "0.0.28",
  recommended_dbos_version: "2.25.0",
  missing_columns: ["workflow_status.attributes", "workflow_status.schedule_name"],
  message: "This database is at DBOS schema revision 38; Argus needs 41.",
};

describe("connection diagnostics helpers", () => {
  it("treats fetch failures as disconnected", () => {
    expect(
      getConnectionIndicatorState({
        fetchError: "network down",
        health: connectedHealth,
        diagnostics: null,
      }),
    ).toBe("disconnected");
  });

  it("treats schema issues as a yellow connected state", () => {
    const diagnostics: SqlDiagnostics = {
      ok: false,
      issues: [
        {
          kind: "missing_column",
          table_name: "workflow_status",
          column_name: "parent_workflow_id",
          expected_type: "text or character varying or character",
          actual_type: null,
          detail: "Missing required column dbos.workflow_status.parent_workflow_id.",
        },
      ],
    };

    expect(
      getConnectionIndicatorState({
        fetchError: null,
        health: connectedHealth,
        diagnostics,
      }),
    ).toBe("issues");
    expect(connectionIndicatorClass("issues")).toBe("text-status-warning");
    expect(connectionIndicatorLabel("issues")).toBe("Connected");
    expect(diagnosticsIssueSummary(diagnostics)).toBe("1 schema issue found");
  });

  it("keeps healthy connections green when diagnostics are clean or absent", () => {
    expect(
      getConnectionIndicatorState({
        fetchError: null,
        health: connectedHealth,
        diagnostics: null,
      }),
    ).toBe("connected");

    expect(
      getConnectionIndicatorState({
        fetchError: null,
        health: connectedHealth,
        diagnostics: { ok: true, issues: [] },
      }),
    ).toBe("connected");
    expect(connectionIndicatorClass("connected")).toBe("text-status-success");
    expect(connectionIndicatorLabel("connected")).toBe("Connected");
    expect(diagnosticsIssueSummary({ ok: true, issues: [] })).toBeNull();
  });
});

describe("DBOS revision compatibility", () => {
  it("flags an outdated revision even when no columns are reported missing", () => {
    const diagnostics: SqlDiagnostics = { ok: true, issues: [], compat: outdatedCompat };

    expect(
      getConnectionIndicatorState({
        fetchError: null,
        health: connectedHealth,
        diagnostics,
      }),
    ).toBe("issues");
    expect(dbosCompatOutdated(diagnostics)).toEqual(outdatedCompat);
    expect(diagnosticsIssueSummary(diagnostics)).toBe(
      "DBOS schema revision 38 — Argus needs 41",
    );
  });

  it("prefers the revision verdict over the raw issue count", () => {
    // Both are the same underlying problem; the pin advice is the useful half.
    const diagnostics: SqlDiagnostics = {
      ok: false,
      issues: [
        {
          kind: "missing_column",
          table_name: "workflow_status",
          column_name: "schedule_name",
          expected_type: "text",
          actual_type: null,
          detail: "Missing required column dbos.workflow_status.schedule_name.",
        },
      ],
      compat: outdatedCompat,
    };

    expect(diagnosticsIssueSummary(diagnostics)).toBe(
      "DBOS schema revision 38 — Argus needs 41",
    );
  });

  it("stays quiet when the revision is current, unknown, or ungraded", () => {
    const current: SqlDiagnostics = { ok: true, issues: [], compat: compatibleCompat };
    // No dbos_migrations table to read: a legacy Alembic-managed database.
    const unknown: SqlDiagnostics = {
      ok: true,
      issues: [],
      compat: { ...compatibleCompat, revision: null },
    };
    // An older server that predates the compat field.
    const ungraded: SqlDiagnostics = { ok: true, issues: [] };

    for (const diagnostics of [current, unknown, ungraded]) {
      expect(dbosCompatOutdated(diagnostics)).toBeNull();
      expect(diagnosticsIssueSummary(diagnostics)).toBeNull();
      expect(
        getConnectionIndicatorState({ fetchError: null, health: connectedHealth, diagnostics }),
      ).toBe("connected");
    }
    expect(dbosCompatOutdated(null)).toBeNull();
  });

  it("builds a copy-pasteable pin command", () => {
    expect(argusPinCommand(outdatedCompat)).toBe("pip install 'dbos-argus==0.0.28'");
    expect(argusPinCommand(compatibleCompat)).toBeNull();
    expect(argusPinCommand(null)).toBeNull();
  });
});
