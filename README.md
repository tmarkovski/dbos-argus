# Argus

**A self-hosted, open-source, read-only workflow viewer for DBOS Transact applications.**

> **Try it live →** [dbos-argus--tmarkovski.replit.app](https://dbos-argus--tmarkovski.replit.app) — hosted demo backed by SQLite with the bundled sample app driving continuous workflow activity. State resets on container restart.

Argus is a web dashboard for visualizing the durable workflows your [DBOS Transact](https://github.com/dbos-inc/dbos-transact-py) apps are already running. It points at the database your DBOS app uses (Postgres or SQLite), opens a read-only connection, and renders the workflow state DBOS already stores there. No agents, no app-side wiring, no schema of its own, no write path.

![Argus dashboard](docs/images/dashboard.png)

![Workflow detail with step graph](docs/images/workflow-detail.png)

> **Status:** Pre-alpha. Everything will change. Not production-ready. Argus is built for development and quick inspection of a running DBOS database.

> **DBOS compatibility.** Each release is validated against a specific DBOS version — see the "Tested against DBOS …" line in [CHANGELOG.md](./CHANGELOG.md) (and in the release notes on the [Releases page](https://github.com/tmarkovski/dbos-argus/releases)), or call `GET /version` (`tested_dbos_version`) on a running instance. Older / newer DBOS versions usually still work; the connection sidebar in the UI flags any schema mismatches it finds.

---

## Quick start

If you already have a DBOS app running, you're 30 seconds away. Point Argus at the same database (Postgres or SQLite) — pick whichever runner is most convenient.

In every case, open http://localhost:8090 once it's up.

### With `uvx` (recommended, no install)

Postgres:

```bash
uvx dbos-argus@latest --db-url "postgresql+asyncpg://USER:PASS@localhost:5432/YOURDB"
```

SQLite (use four slashes for an absolute path):

```bash
uvx dbos-argus@latest --db-url "sqlite:////absolute/path/to/your-app.sqlite"
```

[`uv`](https://docs.astral.sh/uv/) downloads the published wheel, installs it into a throwaway environment, and runs it. The console SPA is bundled inside the wheel — no separate frontend to install. The `@latest` suffix re-resolves the version on each invocation; without it, `uvx` reuses the version it cached the first time you ran the tool.

### With `pip` / `pipx`

```bash
pipx install dbos-argus
dbos-argus --db-url "postgresql+asyncpg://USER:PASS@localhost:5432/YOURDB"
# or:
dbos-argus --db-url "sqlite:////absolute/path/to/your-app.sqlite"
```

### With Docker

```bash
docker run --rm -p 8090:8090 \
  -e ARGUS_DATABASE_URL="postgresql+asyncpg://USER:PASS@host.docker.internal:5432/YOURDB" \
  tmarkovski/dbos-argus:latest
```

For SQLite, mount the database file in and point Argus at the in-container path:

```bash
docker run --rm -p 8090:8090 \
  -v /absolute/path/to/your-app.sqlite:/data/app.sqlite:ro \
  -e ARGUS_DATABASE_URL="sqlite:////data/app.sqlite" \
  tmarkovski/dbos-argus:latest
```

That's it. Argus connects read-only to `dbos.workflow_status` and the related DBOS system tables. Nothing to install in your app.

A few gotchas:

- **Argus runs on asyncpg / aiosqlite.** Bare `postgresql://`, `postgres://`, and `sqlite://` URLs all work — Argus rewrites the scheme to `postgresql+asyncpg://` or `sqlite+aiosqlite://` automatically. Pasting a standard libpq connection string is fine.
- **SQLite paths are absolute by URL convention.** `sqlite:////path/to/file.sqlite` (four slashes) means `/path/to/file.sqlite`. Three slashes makes it relative to the current working directory.
- **Azure Database for PostgreSQL uses TLS.** Argus auto-enables `sslmode=require` for hosts under `*.postgres.database.azure.com`; add an explicit `sslmode=` only if you need to override that default.
- **`host.docker.internal`** (Docker only) is what the container uses to reach Postgres on your host (macOS, Windows, Docker Desktop). On Linux, add `--add-host=host.docker.internal:host-gateway`, or use `--network host` and switch back to `localhost`.
- **`pg_hba.conf`** may reject connections from the docker bridge (`172.17.0.0/16`) by default. If you see auth errors, add a matching `host` line.

Smoke-test the URL first if you're unsure:

```bash
# Postgres
psql "postgresql://USER:PASS@localhost:5432/YOURDB" -c "select count(*) from dbos.workflow_status;"

# SQLite
sqlite3 /absolute/path/to/your-app.sqlite "select count(*) from workflow_status;"
```

If that returns a number, you're good — pass the same database to Argus (swap `localhost` → `host.docker.internal` if using the Docker runner with Postgres).

### Image tags

| Tag | Meaning |
|---|---|
| `:latest` | Latest stable release |
| `:vX.Y.Z` / `:X.Y` / `:X` | Release tags |
| `:sha-<short>` | Per-commit, immutable |

Multi-arch: `linux/amd64` + `linux/arm64`. Pulled from [`tmarkovski/dbos-argus`](https://hub.docker.com/r/tmarkovski/dbos-argus) on Docker Hub.

### Runtime env vars

| Var | Purpose |
|---|---|
| `ARGUS_DATABASE_URL` | SQLAlchemy async URL to the database your DBOS app writes to. Postgres (`postgresql+asyncpg://...`, or bare `postgresql://` / `postgres://` which Argus rewrites) and SQLite (`sqlite+aiosqlite:///...`, or bare `sqlite:///...`) are both supported. |
| `ARGUS_CORS_ORIGINS` | Comma-separated allowed origins for the console / WebSocket. Defaults to `*` since Argus is an unauthenticated dev tool typically bound to localhost; narrow this if you expose Argus beyond localhost. |

## Why Argus exists

We built this because we like [DBOS](https://www.dbos.dev/). A lot.

DBOS Transact takes durable execution — historically the territory of heavy infrastructure like Temporal — and packages it as a library that lives inside your app and persists workflow state to a Postgres database you already have. The core is MIT-licensed, the design has serious academic pedigree ([MIT, Stanford, CMU](https://en.wikipedia.org/wiki/DBOS)), and the API is one of the cleaner ones in this category. It mostly gets out of your way and lets you keep writing normal code that happens to be crash-safe.

When you're building with DBOS, especially in development, you sometimes want a quick local window into the workflows already sitting in Postgres: what ran, what failed, what's waiting, and how parent/child workflows fit together. Argus is that window. MIT, self-hosted, no telemetry, no upsell. Just a read-only viewer for workflow state DBOS is already managing for you.

For production workflow operations, use [DBOS Conductor](https://docs.dbos.dev/production/conductor). Conductor is DBOS's supported management service for production DBOS applications, including distributed workflow recovery, workflow and queue observability, workflow and queue management, managed retention policies, alerting, and hosted or self-hosted deployment options. Argus was made with love for DBOS as a dev-focused companion: something you can point at a running DBOS database to quickly inspect what is happening. It is not production-tested for robust operations, scaling, managed recovery, retention, alerting, or team-wide controls.

If you're experimenting with DBOS or debugging local/dev workflows, you're our audience. Welcome.

Argus is not affiliated with, endorsed by, or sponsored by DBOS Inc.

## What Argus does (and doesn't)

**Does:**
- Read-only live and historical view of every durable workflow, its steps, inputs, outputs, and status
- Visual step-by-step workflow graphs with parent/child workflow lineage, powered by [Svelte Flow](https://svelteflow.dev)
- Filter, search, and group workflow runs by status, name, ID, and time range
- Light and dark mode (because of course)

![Workflows list grouped by parent](docs/images/workflows-list.png)

**Planned:**
- Read-only queue views where DBOS exposes enough state in Postgres
- Better schema compatibility diagnostics as DBOS evolves
- Optional auth for shared dev/internal deployments

**Doesn't:**
- Does not execute, cancel, resume, fork, or recover your workflows. Argus is strictly observability.
- Does not write to your database. Reads only — only from DBOS Transact's `dbos.*` system tables.
- Does not provide Conductor's production operations layer. Use DBOS Conductor when you need managed workflow operations, recovery, scaling, retention, alerting, or team controls.

## How it works

```
┌──────────────┐                       ┌────────────────────────┐
│  DBOS app    │                       │  Argus                 │
│  (Py / TS)   │                       │  FastAPI + console SPA │
└──────┬───────┘                       └────────┬───────────────┘
       │ writes workflow_status                 │ reads workflow_status
       ▼                                        ▼
       ┌────────────────────────────────────────┐
       │       Postgres   or   SQLite           │
       │      (DBOS Transact's system store)    │
       └────────────────────────────────────────┘
```

One database. Your DBOS app keeps writing workflow state to its system tables exactly as it always has. Argus opens a separate read-only connection to the same database and renders what's in those tables. Postgres and SQLite are both supported via a single backend adapter, so the REST and realtime layers behave the same regardless of where DBOS persists.

The console is built as a static SPA and served by the FastAPI process on the same port — one image, one container, no CORS to think about.

## Project layout

This is a pnpm + uv monorepo. Plain root `package.json` scripts fan tasks out to both toolchains (`pnpm -r` for JS, `uv run` for Python).

| Path | Package | Purpose |
|---|---|---|
| `apps/console` | — | SvelteKit console (the web UI) |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend |
| `packages/ui` | `@dbos-argus/ui` (npm) | Reusable Svelte components — workflow graph, status pills |
| `tests/sample-app` | — | Standalone DBOS app you can run to seed your local Postgres with workflows for the dashboard to render |

## Contributing

Early contributors very welcome — especially people already running real DBOS Transact apps who have opinions on what this viewer should show. Before starting work on anything non-trivial, please file an issue or drop by Discussions so we can coordinate.

Principles that will guide code review:

1. **Argus is read-only.** It only reads from DBOS Transact's `dbos.*` system tables. New features should stay on the read path unless the project scope explicitly changes.
2. **The console is a client.** It talks only to the Argus backend, never to Postgres directly.
3. **Boring is good.** FastAPI, Postgres, SvelteKit, Svelte Flow. No clever infrastructure until there is a concrete need.
4. **Typed contracts.** Backend ↔ frontend messages have a single source of truth.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup.

## License

[MIT](./LICENSE).

## Disclaimer

Argus is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by DBOS Inc. "DBOS Transact," "DBOS Conductor," and "DBOS Cloud" are products of DBOS Inc.
