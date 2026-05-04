# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`dbos-argus` is a self-hosted, open-source, read-only workflow viewer for DBOS Transact applications. It is a dev-focused companion for quickly inspecting workflow state in a running DBOS Postgres database; production workflow operations belong in DBOS Conductor. Argus opens a read-only async Postgres connection to the same database the DBOS app uses, and renders what's in `dbos.workflow_status` (and friends) in a SvelteKit UI. No app-side wiring, no agents, no separate Argus-owned schema.

See [README.md](./README.md) for the product framing and architecture diagram; see [docs/architecture.md](./docs/architecture.md) for invariants.

## Repo layout

Mixed-language monorepo: **pnpm workspaces** for JS/TS, **uv workspaces** for Python, **Turborepo** as the cross-language task runner.

| Path | Package | Role |
|---|---|---|
| `apps/console` | `console` (private) | SvelteKit web UI. Only client of the backend. |
| `packages/server` | `dbos-argus` (PyPI) | FastAPI backend. Reads the DBOS system tables directly. |
| `packages/ui` | `@dbos-argus/ui` | Svelte 5 component stubs consumed by the console. |
| `tests/sample-app` | `argus-sample-app` | DBOS dev fixture. Provides four CLI scripts (`argus-runner`, `argus-ops`, `argus-scheduler`, `argus-heartbeat-runner`) installed into the root `.venv` — runner hosts the example workflows, ops drives them (send/cancel/list), scheduler ticks the cron and enqueues heartbeats onto the `argus-heartbeats` queue, heartbeat-runner subscribes as a worker for that queue and executes them. Each runs under its own executor_id. Workspace member; root `uv sync` resolves `dbos` for the whole repo. |

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

The `/api/sql-diagnostics` endpoint diffs the live schema against `packages/server/dbos_argus/data/dbos_schema.json` — the *full* DBOS schema with each column tagged `"argus": true|false` (runtime filters to true). The CI watchdog `.github/workflows/dbos-schema-watch.yml` runs daily, regenerates against the latest DBOS, and opens an issue when anything changes. **When `main.py` starts reading a column that's currently `argus: false`, flip it to `true` in the JSON.** Full procedure in CONTRIBUTING.md → "Schema snapshot".

## Architecture invariants (enforce in code review)

1. **Argus is read-only.** The server only reads from DBOS Transact's `dbos.*` system tables. New features should stay on the read path unless the project scope explicitly changes.
2. **The console is a client of the Argus backend, never of Postgres directly.**
3. **No app-side SDK.** All UI actions are server-mediated. There is no `@dbos-argus/client` package and no WS-app-registry protocol.
4. **Realtime channels mirror REST shapes and go through `ArgusDB`.** Each channel in `packages/server/dbos_argus/realtime/channels/` lazy-imports a `fetch_*` helper from `main.py` (the same helper the REST route calls) so the two transports never drift. Snapshots and cursors run through `db.<method>()` — no raw SQL in channels — so SQLite + Postgres stay supported in lockstep.

## Stack notes that matter

- **Svelte 5 runes** (`$state`, `$props`, `$state.raw`) — *not* Svelte 4 stores. Component props are destructured from `$props()`.
- **Tailwind v4** via `@tailwindcss/vite` plugin — no `tailwind.config.js`. Styles are imported with `@import "tailwindcss";` in `apps/console/src/app.css`.
- **@xyflow/svelte** for workflow graphs; **elkjs** for layout (not dagre).
- **SvelteKit adapter-static** with `fallback: 'index.html'` — the console builds to a static SPA and is served by FastAPI via a catch-all route in `packages/server/dbos_argus/main.py`. No Node process in production.
- **SQLAlchemy 2.x async** + asyncpg, reading directly from the DBOS system schema (`dbos.*`).

## Theming

The console's visual theme is split into two files so shadcn presets can be swapped without touching app code:

- **`apps/console/src/theme.css`** — generated. Holds the preset's `:root` and `.dark` blocks: base palette (background/foreground/card/popover/muted/accent/border/input/ring), `--primary`, `--secondary`, `--destructive`, `--chart-1..5`, sidebar tokens, `--radius`, `--font-sans`, `--font-heading`. Header comment records the preset code. **Do not hand-edit.**
- **`apps/console/src/app.css`** — hand-maintained. Imports `theme.css`, declares Argus-specific tokens that survive preset swaps (`--status-success/running/queued/warning/error`, `--highlight*`, `--font-mono`), registers everything in `@theme inline`, and holds `@layer base`.

To swap to a new preset:

1. Pick a preset at https://ui.shadcn.com/create — the URL ends with `?preset=<code>`.
2. `pnpm --filter console theme:sync <code>` — regenerates `theme.css` and prints the font packages to install.
3. Update the `@fontsource-variable/<name>` `@import` lines in `app.css` to match the new `--font-sans` / `--font-heading`, and `pnpm --filter console add/remove` the corresponding fontsource packages.
4. Verify with `pnpm run lint && pnpm run build`.

The script (`apps/console/scripts/sync-theme.sh`) decodes the preset, spawns a scratch Next.js project, runs `npx shadcn apply --preset <code> --only theme`, and copies the resulting `:root`/`.dark` blocks into `theme.css`. The scratch project exists because the React shadcn CLI requires a Next/Vite project structure that `shadcn-svelte`'s `components.json` doesn't satisfy.

Workflow status colors (`--status-*`) are intentionally outside the preset so SUCCESS stays green, ERROR stays red, etc. across themes. If a preset's primary clashes badly with a status hue, override the status block in `app.css`.

## CI

Three GitHub Actions workflows:
- `.github/workflows/ci-python.yml` — uv + ruff + pytest for `packages/server` and the example.
- `.github/workflows/ci-node.yml` — pnpm + turbo lint/test/build for `apps/**` and the TS packages.
- `.github/workflows/release.yml` — fires on `v*` tags. Three sequenced jobs: `pypi` (OIDC trusted publishing) → `docker` (multi-arch push to `tmarkovski/dbos-argus`) → `release` (GitHub Release with CHANGELOG body). See **Releasing** in `CONTRIBUTING.md`.

## Releasing

Tag-driven. Bump `CHANGELOG.md` (move `[Unreleased]` → dated `[X.Y.Z]`), commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`. Version comes from `hatch-vcs` reading the tag — nothing to bump in `pyproject.toml` or `__init__.py`. PyPI rejects re-uploading the same version, so each release must bump.
