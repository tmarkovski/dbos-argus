# python-hello-workflow

Minimal DBOS Transact app wired up to Argus. Scaffold only — end-to-end integration is not yet implemented.

## Run

```bash
cd examples/python-hello-workflow
uv sync
uv run python main.py
```

With the full dev stack up (`docker compose up` from the repo root), `main.py` will:

1. Execute a single `@DBOS.workflow()` locally.
2. Open a WebSocket to `ws://localhost:8090/ws/apps` and log the greeting frame Argus sends back.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARGUS_URL` | `ws://localhost:8090/ws/apps` | Argus backend WS endpoint |
| `ARGUS_API_KEY` | `local-dev-key` | Placeholder API key — real auth is not implemented yet |
