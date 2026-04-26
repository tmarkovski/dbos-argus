# Argus

**A self-hosted, open-source management console for DBOS Transact applications.**

Argus is a web dashboard for observing the durable workflows your [DBOS Transact](https://github.com/dbos-inc/dbos-transact-py) apps are already running. It points at the Postgres database your DBOS app uses, reads its workflow tables directly, and gives you a UI on top. No agents, no app-side wiring, no schema of its own.

> **Status:** Pre-alpha. Everything will change. Not production-ready. If you're here early, welcome — the issue tracker and Discussions are the best place to have a say in where this goes.

---

## Quick start

If you already have a DBOS app running against Postgres, you're 30 seconds away. Point Argus at the same database:

```bash
docker run --rm -p 8090:8090 \
  -e ARGUS_DATABASE_URL="postgresql+asyncpg://USER:PASS@host.docker.internal:5432/YOURDB" \
  tmarkovski/dbos-argus:edge
```

Open http://localhost:8090.

That's it. Argus is read-only against `dbos.workflow_status` and the related DBOS system tables, so it can't break anything. Nothing to install in your app.

A few gotchas:

- **Driver must be asyncpg.** The URL prefix is `postgresql+asyncpg://`, not `postgresql://`.
- **`host.docker.internal`** is what the container uses to reach Postgres on your host (macOS, Windows, Docker Desktop). On Linux, add `--add-host=host.docker.internal:host-gateway`, or use `--network host` and switch back to `localhost`.
- **`pg_hba.conf`** may reject connections from the docker bridge (`172.17.0.0/16`) by default. If you see auth errors, add a matching `host` line.

Smoke-test the URL first if you're unsure:

```bash
psql "postgresql://USER:PASS@localhost:5432/YOURDB" -c "select count(*) from dbos.workflow_status;"
```

If that returns a number, you're good — swap `localhost` → `host.docker.internal` and `postgresql://` → `postgresql+asyncpg://` in the docker command.

### Image tags

| Tag | Meaning |
|---|---|
| `:edge` | Built from every push to `main` |
| `:vX.Y.Z` / `:X.Y` / `:X` | Release tags |
| `:sha-<short>` | Per-commit, immutable |

Multi-arch: `linux/amd64` + `linux/arm64`. Pulled from [`tmarkovski/dbos-argus`](https://hub.docker.com/r/tmarkovski/dbos-argus) on Docker Hub.

### Runtime env vars

| Var | Purpose |
|---|---|
| `ARGUS_DATABASE_URL` | SQLAlchemy async URL to the Postgres your DBOS app writes to (must use `postgresql+asyncpg://`) |
| `ARGUS_CORS_ORIGINS` | Comma-separated allowed origins (only needed if the console is served from a different host than the API) |

## Why Argus exists

We built this because we like [DBOS](https://www.dbos.dev/). A lot.

DBOS Transact takes durable execution — historically the territory of heavy infrastructure like Temporal — and packages it as a library that lives inside your app and persists workflow state to a Postgres database you already have. The core is MIT-licensed, the design has serious academic pedigree ([MIT, Stanford, CMU](https://en.wikipedia.org/wiki/DBOS)), and the API is one of the cleaner ones in this category. It mostly gets out of your way and lets you keep writing normal code that happens to be crash-safe.

Once you're running real workflows, you eventually want a window into them — what's running, what failed, what's stuck — and a friendly way to nudge things along. Argus is that window. MIT, self-hosted, no telemetry, no upsell. Just a UI for the workflows DBOS is already managing for you.

If you're already using DBOS and nodding along, you're our audience. Welcome.

Argus is not affiliated with, endorsed by, or sponsored by DBOS Inc.

## What Argus does (and doesn't)

**Does:**
- Live and historical view of every durable workflow, its steps, inputs, outputs, and status
- Visual step-by-step workflow graphs with parent/child workflow lineage, powered by [Svelte Flow](https://svelteflow.dev)
- Filter, search, and group workflow runs by status, name, ID, and time range
- Light and dark mode (because of course)

**Planned:**
- Cancel, resume, restart, and fork workflows from the dashboard
- Inspect and manage DBOS distributed queues
- Alerts for failed workflows and queue backlogs

**Doesn't:**
- Does not execute your workflows. Argus is strictly observability.
- Does not write to your database. Reads only — only from DBOS Transact's `dbos.*` system tables.
- Does not replace DBOS Transact. You install the library in your app the normal way; Argus is a separate process that happens to look at the same Postgres.

## How it works

```
┌──────────────┐                       ┌────────────────────────┐
│  DBOS app    │                       │  Argus                 │
│  (Py / TS)   │                       │  FastAPI + console SPA │
└──────┬───────┘                       └────────┬───────────────┘
       │ writes dbos.workflow_status            │ reads dbos.workflow_status
       ▼                                        ▼
       ┌────────────────────────────────────────┐
       │             Postgres                   │
       │   (DBOS Transact's system schema)      │
       └────────────────────────────────────────┘
```

One Postgres. Your DBOS app keeps writing workflow state to its `dbos.*` system tables exactly as it always has. Argus opens a separate read-only connection to the same database and renders what's in those tables.

The console is built as a static SPA and served by the FastAPI process on the same port — one image, one container, no CORS to think about.

## Project layout

This is a pnpm + uv monorepo orchestrated with Turborepo.

| Path | Package | Purpose |
|---|---|---|
| `apps/console` | — | SvelteKit console (the web UI) |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend |
| `packages/ui` | `@dbos-argus/ui` (npm) | Reusable Svelte components — workflow graph, status pills |
| `tests/sample-app` | — | Standalone DBOS app you can run to seed your local Postgres with workflows for the dashboard to render |

## Contributing

Early contributors very welcome — especially people already running DBOS Transact in production who have opinions on what this console should look like. Before starting work on anything non-trivial, please file an issue or drop by Discussions so we can coordinate.

Principles that will guide code review:

1. **Argus is read-mostly.** It only reads from DBOS Transact's `dbos.*` system tables. Future write actions (cancel, resume, fork) will go through DBOS Transact's own APIs, not raw SQL.
2. **The console is a client.** It talks only to the Argus backend, never to Postgres directly.
3. **Boring is good.** FastAPI, Postgres, SvelteKit, Svelte Flow. No clever infrastructure until there is a concrete need.
4. **Typed contracts.** Backend ↔ frontend messages have a single source of truth.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup.

## License

[MIT](./LICENSE).

## Disclaimer

Argus is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by DBOS Inc. "DBOS Transact," "DBOS Conductor," and "DBOS Cloud" are products of DBOS Inc.
