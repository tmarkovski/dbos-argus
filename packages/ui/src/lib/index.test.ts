import { describe, expect, it } from "vitest";
import type {
  EventTimelineProps,
  QueueTableProps,
  StatusPillProps,
  WorkflowGraphProps,
  WorkflowStatus,
} from "./types.js";

describe("@dbos-argus/ui types", () => {
  it("status pill accepts a known status", () => {
    const status: WorkflowStatus = "running";
    const p: StatusPillProps = { status, label: "Running" };
    expect(p.status).toBe("running");
  });

  it("workflow graph props require nodes and edges", () => {
    const p: WorkflowGraphProps = { nodes: [], edges: [] };
    expect(p.nodes.length).toBe(0);
  });

  it("event timeline props require events", () => {
    const p: EventTimelineProps = { events: [] };
    expect(Array.isArray(p.events)).toBe(true);
  });

  it("queue table props require queues", () => {
    const p: QueueTableProps = { queues: [] };
    expect(Array.isArray(p.queues)).toBe(true);
  });
});
