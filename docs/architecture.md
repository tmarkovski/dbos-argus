# Architecture

This is a stub. The authoritative architecture overview lives in the project [README](../README.md#how-it-works).

## Components

- **DBOS application** (customer code) — a Python or TypeScript service using `dbos-transact`. Writes its workflow state to a Postgres database. Argus does not touch the application process at all.
- **Postgres** — the same database the DBOS application uses. Argus opens its own read-only async connection and queries the `dbos.*` system schema.
- **Argus backend** (`packages/server`) — FastAPI service. Reads `dbos.workflow_status` and related tables; serves the read API consumed by the console.
- **Argus console** (`apps/console`) — SvelteKit UI built as a static SPA and served by the FastAPI process on the same port. The only client of the Argus backend.

## Invariants

1. Argus is a separate process. It does not run inside the DBOS application and the application does not need to know Argus exists.
2. Argus reads only from the `dbos.*` system schema. It does not own a schema, run migrations, or write to user tables.
3. The console communicates only with the Argus backend over HTTP and WebSocket. There is no client-side SDK or app-side connection protocol.

## Realtime layer

Live updates flow over a single multiplexed WebSocket at `/ws`. The console keeps one connection open and rides it for every page; subscriptions are tagged by client-assigned `sub_id`. Server-side pollers replace the per-page `setInterval` fetches that the console used to issue.

- **Channels** (`packages/server/dbos_argus/realtime/channels/`): one class per channel. `BroadcastChannel` (no params, single shared poller) covers `health`, `stats`, `schedules`. `KeyedChannel` (one poller per distinct params hash, refcounted) covers `workflows`, `workflow`, `notifications`, `stats.timeseries`.
- **Cursor gate**: each tick runs a cheap "did anything change?" query (e.g. `(max(updated_at), count(*))`); the heavier snapshot only re-runs when the cursor advances. Pollers shut down automatically when their last subscriber disconnects.
- **Wire protocol**: client sends `{type: "subscribe" | "unsubscribe" | "update_params" | "ping", sub_id, channel?, params?}`; server replies with `snapshot`, `update`, `error`, `ack`, or `pong`. `update_params` re-keys an existing subscription on the server without churning the client UI.
- **Payloads**: each channel emits the same JSON shape as its REST counterpart (`/api/workflows`, `/api/workflows/{id}`, `/api/stats`, etc). REST routes remain authoritative for curl/debug — the WS layer is purely additive.
- **Frontend**: `apps/console/src/lib/realtime/` provides a singleton `RealtimeClient` (lazy connect, exponential backoff, sub replay on reconnect, heartbeat ping/pong) and a `createSubscription<T>` helper. Pages typically `realtimeClient.subscribe(channel, params, handlers)` in `onMount` and dispose in `onDestroy`.

## Future topics (not yet documented)

- Read-only queue views where DBOS exposes enough state in Postgres.
- Authentication and RBAC.
- Deployment notes for shared dev/internal use.
