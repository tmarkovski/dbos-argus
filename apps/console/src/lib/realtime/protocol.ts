/**
 * Wire protocol for the /ws endpoint.
 *
 * Mirrors `packages/server/dbos_argus/realtime/protocol.py`. Channel-specific
 * payload shapes are deliberately `unknown` here — typed wrappers in
 * `subscribe.svelte.ts` and channel-specific stores narrow them down.
 */

export type SubscribeMessage = {
  type: "subscribe";
  sub_id: string;
  channel: string;
  params?: Record<string, unknown>;
};

export type UnsubscribeMessage = {
  type: "unsubscribe";
  sub_id: string;
};

export type UpdateParamsMessage = {
  type: "update_params";
  sub_id: string;
  params?: Record<string, unknown>;
};

export type PingMessage = { type: "ping" };

export type ClientMessage =
  | SubscribeMessage
  | UnsubscribeMessage
  | UpdateParamsMessage
  | PingMessage;

export type SnapshotMessage = {
  type: "snapshot";
  sub_id: string;
  channel: string;
  data: unknown;
};

export type UpdateMessage = {
  type: "update";
  sub_id: string;
  channel: string;
  data: unknown;
};

export type ErrorMessage = {
  type: "error";
  sub_id?: string | null;
  code: string;
  message: string;
};

export type PongMessage = { type: "pong" };

export type AckMessage = {
  type: "ack";
  sub_id: string;
  op: "subscribe" | "unsubscribe" | "update_params";
};

export type ServerMessage =
  | SnapshotMessage
  | UpdateMessage
  | ErrorMessage
  | PongMessage
  | AckMessage;

export type ConnectionStatus = "closed" | "connecting" | "open";
