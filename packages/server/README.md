# dbos-argus

**Self-hosted, read-only workflow viewer for [DBOS Transact](https://github.com/dbos-inc/dbos-transact-py).**

Argus is a web dashboard for the durable workflows your DBOS apps are already running. It opens a read-only connection to the same Postgres your DBOS app uses and renders the workflow state from `dbos.workflow_status` and friends. No agents, no app-side wiring, no schema of its own.

This is the PyPI package: a FastAPI backend with the SvelteKit console SPA bundled inside the wheel. One `uvx` away.

![Argus dashboard](https://raw.githubusercontent.com/tmarkovski/dbos-argus/main/docs/images/dashboard.png)

![Workflow detail with step graph](https://raw.githubusercontent.com/tmarkovski/dbos-argus/main/docs/images/workflow-detail.png)

> For production workflow operations, use [DBOS Conductor](https://docs.dbos.dev/production/conductor) — the DBOS-supported management service for recovery, retention, alerting, and team controls. Argus is a dev-focused companion for inspecting workflow state.

## Quick start

Point at the same Postgres your DBOS app writes to. Open http://localhost:8090.

### `uvx` (no install)

```bash
uvx dbos-argus --db-url "postgresql://USER:PASS@localhost:5432/YOURDB"
```

### `pipx`

```bash
pipx install dbos-argus
dbos-argus --db-url "postgresql://USER:PASS@localhost:5432/YOURDB"
```

### Docker

```bash
docker run --rm -p 8090:8090 \
  -e ARGUS_DATABASE_URL="postgresql://USER:PASS@host.docker.internal:5432/YOURDB" \
  tmarkovski/dbos-argus:latest
```

A bare `postgresql://` URL is fine — Argus rewrites the scheme to `postgresql+asyncpg://` for you. For Azure Database for PostgreSQL hosts, `sslmode=require` is enabled by default.

## Configuration

| | Purpose |
|---|---|
| `--db-url` / `ARGUS_DATABASE_URL` | Postgres URL your DBOS app writes to |
| `ARGUS_CORS_ORIGINS` | Comma-separated allowed origins (only when serving the console from a different host than the API) |

`dbos-argus --help` for the full flag list.

## More

Full project docs, CHANGELOG, contributing guide, and the source for the SvelteKit console all live in the monorepo: [github.com/tmarkovski/dbos-argus](https://github.com/tmarkovski/dbos-argus).

MIT licensed. Not affiliated with DBOS Inc.
