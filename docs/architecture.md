# Architecture

This is a stub. The authoritative architecture overview lives in the project [README](../README.md#how-it-works).

## Components

- **DBOS application** (customer code) — a Python or TypeScript service using `dbos-transact`. Writes its workflow state to a Postgres database. Argus does not touch the application process at all.
- **Postgres** — the same database the DBOS application uses. Argus opens its own read-only async connection and queries the `dbos.*` system schema.
- **Argus backend** (`packages/server`) — FastAPI service. Reads `dbos.workflow_status` and related tables; serves the management API consumed by the console.
- **Argus console** (`apps/console`) — SvelteKit UI built as a static SPA and served by the FastAPI process on the same port. The only client of the Argus backend.

## Invariants

1. Argus is a separate process. It does not run inside the DBOS application and the application does not need to know Argus exists.
2. Argus reads only from the `dbos.*` system schema. It does not own a schema, run migrations, or write to user tables.
3. The console communicates only with the Argus backend over HTTP. There is no client-side SDK or app-side connection protocol.

## Future topics (not yet documented)

- Workflow intervention API (cancel / resume / restart / fork) — implemented by the server invoking DBOS Transact's management APIs against the same database.
- Live updates from server to console (likely via SSE or WebSocket) to replace polling.
- Authentication and RBAC.
- Multi-instance / high-availability deployment.
