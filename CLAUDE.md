# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`dbos-argus` is a self-hosted, open-source management console for DBOS Transact applications — an MIT-licensed alternative to the proprietary DBOS Conductor. DBOS apps connect *outbound* over WebSocket to the Argus backend; Argus never opens connections into apps and never touches the app's database.

See [README.md](./README.md) for the product framing and architecture diagram; see [docs/architecture.md](./docs/architecture.md) for invariants.

## Repo layout

Mixed-language monorepo: **pnpm workspaces** for JS/TS, **uv workspaces** for Python, **Turborepo** as the cross-language task runner.

| Path | Package | Role |
|---|---|---|
| `apps/console` | `console` (private) | SvelteKit web UI. Only client of the backend. |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend. The only service that touches the Argus DB. |
| `packages/ui` | `@dbos-argus/ui` | Svelte 5 component stubs consumed by the console. |
| `packages/client-ts` | `@dbos-argus/client` | TS WS client for DBOS TS apps. |
| `examples/python-hello-workflow` | — | Standalone DBOS app scaffold. **Not** a uv workspace member — it has `dbos` as a dep and its own `pyproject.toml` so root `uv sync` isn't blocked on it. |
| `scripts/gen_protocol.py` | — | Regenerates `packages/client-ts/src/protocol.ts` from the Pydantic models. |

## Common commands

First-time setup:

```bash
pnpm install
uv sync
```

Cross-language tasks (Turbo fans out to all packages):

```bash
pnpm run lint      # ruff + svelte-check + tsc across all workspaces
pnpm run test      # pytest + vitest across all workspaces
pnpm run build     # SvelteKit build + tsc --noEmit for libs
```

Turbo is invoked with `--filter=*` from the root scripts so it always runs against every workspace, regardless of git state.

Targeted tasks:

```bash
pnpm --filter console dev              # SvelteKit dev on :5173
pnpm --filter @dbos-argus/client test  # one package's tests
uv run pytest packages/server/tests    # all server tests
uv run pytest packages/server/tests/test_healthz.py::test_ws_apps_sends_hello  # single test
uv run ruff check packages/server      # python lint
uv run ruff format packages/server     # python format
```

Full dev stack in Docker (postgres + bundled argus):

```bash
docker compose up         # postgres + argus (FastAPI + built console SPA)
docker compose up -d      # detached
docker compose logs -f argus
```

Endpoints when up (single port):
- Console SPA: http://localhost:8090/
- API healthz: http://localhost:8090/healthz
- WS: ws://localhost:8090/ws/apps?api_key=…
- Postgres: localhost:5432 (user/pass/db = `argus/argus/argus`)

Pure frontend dev (HMR): `pnpm --filter console dev` starts Vite on :5173 and proxies `/healthz`, `/version`, `/ws/*` to a locally running server on :8090 (set `ARGUS_BACKEND_URL` to override).

Database migrations (alembic runs on container startup; run manually with):

```bash
uv run alembic -c packages/server/alembic.ini upgrade head
uv run alembic -c packages/server/alembic.ini revision --autogenerate -m "message"
```

Regenerating the WS protocol TS types after editing `packages/server/dbos_argus/protocol.py`:

```bash
pnpm run gen:protocol
```

The generated `packages/client-ts/src/protocol.ts` is checked in.

## Architecture invariants (enforce in code review)

1. **Argus is out-of-band.** No code path in this repo may require direct access to a DBOS app's database. `packages/server/pyproject.toml` must not depend on `dbos-transact`.
2. **The console is a client of the Argus backend, never of DBOS apps directly.**
3. **Typed WS contracts.** The Pydantic models in `packages/server/dbos_argus/protocol.py` are the single source of truth. Do not hand-edit `packages/client-ts/src/protocol.ts` — regenerate it.
4. **Forward-compatible auth.** The `apps.api_key_hash` column exists; `# TODO(auth):` markers are where the verification logic will live. No real auth is implemented yet.

## Stack notes that matter

- **Svelte 5 runes** (`$state`, `$props`, `$state.raw`) — *not* Svelte 4 stores. Component props are destructured from `$props()`.
- **Tailwind v4** via `@tailwindcss/vite` plugin — no `tailwind.config.js`. Styles are imported with `@import "tailwindcss";` in `apps/console/src/app.css`.
- **@xyflow/svelte** for workflow graphs; **elkjs** for layout (not dagre).
- **SvelteKit adapter-static** with `fallback: 'index.html'` — the console builds to a static SPA and is served by FastAPI via a catch-all route in `packages/server/dbos_argus/main.py`. No Node process in production.
- **FastAPI native WebSockets** (`@app.websocket(...)`), not a third-party lib.
- **SQLAlchemy 2.x async** + asyncpg. Alembic uses the same engine via `alembic/env.py`.

## CI

Two GitHub Actions workflows trigger only on changes to their respective trees:
- `.github/workflows/ci-python.yml` — uv + ruff + pytest for `packages/server` and the example.
- `.github/workflows/ci-node.yml` — pnpm + turbo lint/test/build for `apps/**` and the TS packages.
