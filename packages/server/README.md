# dbos-argus (server)

FastAPI backend for [Argus](https://github.com/tmarkovski/dbos-argus), a self-hosted management console for DBOS Transact.

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
