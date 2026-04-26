# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`dbos-argus` is a self-hosted, open-source management console for DBOS Transact applications — an MIT-licensed alternative to the proprietary DBOS Conductor. Argus opens a read-only async Postgres connection to the same database the DBOS app uses, and renders what's in `dbos.workflow_status` (and friends) in a SvelteKit UI. No app-side wiring, no agents, no separate Argus-owned schema.

See [README.md](./README.md) for the product framing and architecture diagram; see [docs/architecture.md](./docs/architecture.md) for invariants.

## Repo layout

Mixed-language monorepo: **pnpm workspaces** for JS/TS, **uv workspaces** for Python, **Turborepo** as the cross-language task runner.

| Path | Package | Role |
|---|---|---|
| `apps/console` | `console` (private) | SvelteKit web UI. Only client of the backend. |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend. Reads the DBOS system tables directly. |
| `packages/ui` | `@dbos-argus/ui` | Svelte 5 component stubs consumed by the console. |
| `tests/sample-app` | — | Standalone DBOS app used as a dev fixture — runs a few workflows so the dashboard has data to render. **Not** a uv workspace member; has its own `pyproject.toml` so root `uv sync` isn't blocked on the `dbos` dep. |

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
uv run pytest packages/server/tests    # all server tests
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
- Postgres: localhost:5432 (user/pass/db = `argus/argus/argus`)

Pure frontend dev (HMR): `pnpm --filter console dev` starts Vite on :5173 and proxies `/healthz`, `/version` to a locally running server on :8090 (set `ARGUS_BACKEND_URL` to override).

Argus does not own a schema. It reads DBOS Transact's system tables (`dbos.workflow_status`, etc.) from the Postgres DB that the DBOS app also uses. No migrations to run.

## Architecture invariants (enforce in code review)

1. **Argus is read-mostly today.** The server only reads from DBOS Transact's `dbos.*` system tables. When write actions land (cancel/resume/fork), they will go through DBOS Transact's own management APIs from inside the server process — not raw SQL — and `packages/server/pyproject.toml` will then take a runtime dep on `dbos`.
2. **The console is a client of the Argus backend, never of Postgres directly.**
3. **No app-side SDK.** All UI actions are server-mediated. There is no `@dbos-argus/client` package and no WS-app-registry protocol.

## Stack notes that matter

- **Svelte 5 runes** (`$state`, `$props`, `$state.raw`) — *not* Svelte 4 stores. Component props are destructured from `$props()`.
- **Tailwind v4** via `@tailwindcss/vite` plugin — no `tailwind.config.js`. Styles are imported with `@import "tailwindcss";` in `apps/console/src/app.css`.
- **@xyflow/svelte** for workflow graphs; **elkjs** for layout (not dagre).
- **SvelteKit adapter-static** with `fallback: 'index.html'` — the console builds to a static SPA and is served by FastAPI via a catch-all route in `packages/server/dbos_argus/main.py`. No Node process in production.
- **SQLAlchemy 2.x async** + asyncpg, reading directly from the DBOS system schema (`dbos.*`).

## CI

Two GitHub Actions workflows trigger only on changes to their respective trees:
- `.github/workflows/ci-python.yml` — uv + ruff + pytest for `packages/server` and the example.
- `.github/workflows/ci-node.yml` — pnpm + turbo lint/test/build for `apps/**` and the TS packages.
