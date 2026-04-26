# sample-app

Standalone DBOS Transact app used as a dev fixture for Argus. Running it writes a handful of workflows (a linear pipeline, a 20-step loop, a parent with mixed-fate children) into `dbos.workflow_status` so the dashboard has something to render.

## Run

```bash
cd tests/sample-app
uv sync
uv run python main.py
```

Then point Argus at the same Postgres and you'll see the workflows in the UI.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBOS_SYSTEM_DATABASE_URL` | `postgresql://argus:argus@localhost:5432/argus` | Postgres DBOS Transact writes its workflow tables to |
