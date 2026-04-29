import { describe, expect, it } from "vitest";

import {
  connectionIndicatorClass,
  connectionIndicatorLabel,
  diagnosticsIssueSummary,
  getConnectionIndicatorState,
  type Health,
  type SqlDiagnostics,
} from "./connection-diagnostics.js";

const connectedHealth: Health = {
  status: "ok",
  database: "up",
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
    expect(connectionIndicatorClass("issues")).toBe("text-amber-500");
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
    expect(connectionIndicatorClass("connected")).toBe("text-green-500");
    expect(connectionIndicatorLabel("connected")).toBe("Connected");
    expect(diagnosticsIssueSummary({ ok: true, issues: [] })).toBeNull();
  });
});
