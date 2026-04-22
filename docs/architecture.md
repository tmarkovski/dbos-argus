# Architecture

This is a stub. The authoritative architecture overview lives in the project [README](../README.md#architecture).

## Components

- **DBOS application** (customer code) — a Python or TypeScript service using `dbos-transact`. Opens an outbound WebSocket to the Argus backend.
- **Argus backend** (`packages/server`) — FastAPI service. Accepts WebSocket connections from DBOS apps, serves the management API consumed by the console.
- **Argus database** — Postgres. Stores the app registry, event history, operator actions. Entirely separate from any DBOS application database.
- **Argus console** (`apps/console`) — SvelteKit UI. The only client of the Argus backend. Never talks to DBOS apps directly.

## Invariants

1. Argus does not read or write the DBOS application's database.
2. Connections flow outbound from DBOS apps to Argus. Argus does not initiate connections to apps.
3. The console communicates only with the Argus backend.
4. Messages on the WebSocket are defined by Pydantic models in `packages/server/dbos_argus/protocol.py`. The TypeScript mirror in `packages/client-ts/src/protocol.ts` is generated from them.

## Future topics (not yet documented)

- Authentication model (API keys, session handling, RBAC).
- Event log durability and replay semantics.
- Workflow intervention API (cancel / resume / restart / fork).
- Multi-instance / high-availability deployment.
