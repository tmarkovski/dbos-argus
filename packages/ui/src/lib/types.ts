export type WorkflowStatus =
  | "pending"
  | "running"
  | "success"
  | "error"
  | "cancelled"
  | "paused";

export interface WorkflowNode {
  id: string;
  label: string;
  status: WorkflowStatus;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
}

export interface WorkflowGraphProps {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface StatusPillProps {
  status: WorkflowStatus;
  label?: string;
}

export interface TimelineEvent {
  id: string;
  at: string; // ISO timestamp
  label: string;
  detail?: string;
}

export interface EventTimelineProps {
  events: TimelineEvent[];
}

export interface QueueRow {
  id: string;
  name: string;
  pending: number;
  running: number;
  failed: number;
}

export interface QueueTableProps {
  queues: QueueRow[];
}
