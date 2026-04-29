# dbos-argus (server)

FastAPI backend for [Argus](https://github.com/tmarkovski/dbos-argus), a self-hosted, read-only workflow viewer for DBOS Transact.

Argus is built for development and quick inspection of a running DBOS database. It opens a read-only connection to the Postgres database your DBOS app already uses and renders the workflow state stored in DBOS system tables.

For production workflow operations, use [DBOS Conductor](https://docs.dbos.dev/production/conductor), the DBOS-supported management service for recovery, workflow and queue operations, retention, alerting, scaling, and team controls.

This is the PyPI-published package. The console, client libraries, and full project docs live in the [monorepo root](https://github.com/tmarkovski/dbos-argus).

## Install

```bash
uv add dbos-argus
```

## Run

```bash
uv run uvicorn dbos_argus.main:app --host 0.0.0.0 --port 8090
```

The server expects a Postgres database; set `ARGUS_DATABASE_URL`, e.g.:

```
ARGUS_DATABASE_URL=postgresql+asyncpg://argus:argus@localhost:5432/argus
```

See the [repo README](https://github.com/tmarkovski/dbos-argus) for the full stack.
