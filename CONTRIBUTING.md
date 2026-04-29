# Contributing to Argus

Thanks for your interest in the project. Argus is pre-alpha — everything moves fast and breaks fast. If you're planning anything non-trivial, file an issue or start a Discussion first so we can coordinate.

## Development setup

You need:

- Node.js 20 or newer
- pnpm 9 or newer (`npm i -g pnpm`)
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker + Docker Compose (for the full dev stack)

Clone and install:

```bash
git clone https://github.com/tmarkovski/dbos-argus.git
cd dbos-argus
pnpm install
uv sync
```

Bring up the full dev stack (Postgres + server + console):

```bash
docker compose up
```

- Console: http://localhost:5173
- Server healthz: http://localhost:8090/healthz
- Postgres: localhost:5432 (user `argus`, password `argus`, db `argus`)

## Workspace layout

- `apps/console` — SvelteKit web UI
- `packages/server` — FastAPI backend (`dbos-argus` on PyPI)
- `packages/ui` — reusable Svelte 5 components (`@dbos-argus/ui`)
- `tests/sample-app` — standalone DBOS app run manually to seed workflow data into your local Postgres so the dashboard has something to render

## Common commands

```bash
pnpm run lint     # turbo run lint across all packages
pnpm run test     # turbo run test across all packages
pnpm run build    # turbo run build (console + libs)
pnpm run dev      # turbo run dev (all dev servers)
```

Python-only commands run through `uv`:

```bash
uv run ruff check packages/server
uv run pytest packages/server
```

## Code style

- Python: `ruff` for both format and lint. Run `uv run ruff format` before pushing.
- TypeScript / Svelte: `prettier` + the SvelteKit project config. Run `pnpm run lint`.
- Commit messages: imperative mood ("add", "fix", "refactor"), scoped where helpful (`server:`, `console:`, `ui:`).

## Schema snapshot (`dbos_schema.json`)

The `/api/sql-diagnostics` endpoint compares the live `dbos.*` schema against a checked-in snapshot at `packages/server/dbos_argus/data/dbos_schema.json`. The snapshot is the **full DBOS Postgres schema** — every table and column DBOS ships — with each column tagged `"argus": true|false` indicating whether the Argus backend actively reads it. At runtime the diagnostics filter to `argus: true` columns; the watchdog uses the unfiltered snapshot.

The generic dump/diff machinery (`schema_dump.py`, `schema_diff.py`) has no DBOS-specific knowledge.

**The CI watchdog regenerates this for you.** `.github/workflows/dbos-schema-watch.yml` runs daily, pulls the latest DBOS from PyPI, bootstraps its schema in a Postgres service container, and opens an issue if anything changed. The issue body bundles a regenerated `dbos_schema.json` you can paste in. There's no PR creation — when the breakage section is non-empty you'll typically need code edits in `packages/server/dbos_argus/main.py` too, so the issue is the right human checkpoint.

**Manual regeneration** (if you can't wait for the cron, or want to verify locally):

```bash
# Stand up a fresh DBOS DB and bootstrap the schema:
docker compose up -d postgres
uv run --with dbos --with psycopg2-binary --with sqlalchemy \
  python scripts/dbos_schema_bootstrap.py 'postgres://argus:argus@localhost:5432/argus'

# Compare against the checked-in snapshot. Exit code 1 means drift.
uv run --with asyncpg --with sqlalchemy \
  python scripts/dbos_schema_compare.py \
    --db-url 'postgresql+asyncpg://argus:argus@localhost:5432/argus' \
    --new-dbos-version "$(uv run python -c 'import importlib.metadata as m; print(m.version("dbos"))')" \
    --report-file /tmp/report.md \
    --regenerated-file /tmp/regenerated.json
```

**When you adopt a new DBOS column** (flipping `argus: true` and adding a query in `main.py`), bump it in the snapshot directly. The watchdog only carries flags forward — it never sets `argus: true`.

## Releasing

Releases are tag-driven — pushing a `v*` tag fires `.github/workflows/release.yml`, which publishes to PyPI, builds and pushes the multi-arch Docker image, and creates the GitHub Release.

```bash
# 1. Move the [Unreleased] entries in CHANGELOG.md into a new
#    `## [X.Y.Z] - YYYY-MM-DD` section, and add the link reference at the bottom.
#    Keep the "Tested against DBOS …" line — it should match the
#    meta.dbos_version in packages/server/dbos_argus/data/dbos_schema.json.
#    Re-add a fresh "Tested against DBOS …" line at the top of [Unreleased].
# 2. Commit and push.
git commit -am "release vX.Y.Z"
git push

# 3. Tag and push the tag. The pipeline takes it from here.
git tag vX.Y.Z
git push origin vX.Y.Z
```

The workflow has three sequenced jobs:

1. **`pypi`** — `scripts/build-pypi.sh` builds the wheel (with the SvelteKit SPA bundled at `dbos_argus/_console/`); `uv publish` uploads via OIDC trusted publishing to the `pypi` GitHub environment.
2. **`docker`** — depends on `pypi` so `pip install dbos-argus==<ver>` in the image can't race the upload. Pushes `:X.Y.Z`, `:X.Y`, `:X`, `:latest` (stable only), and `:sha-<short>` to Docker Hub.
3. **`release`** — depends on both. Creates the GitHub Release with the matching CHANGELOG section as body (auto-generated commit list as fallback).

**Versioning.** Source of truth is the git tag — version is computed by `hatch-vcs` at build time. There's nothing to bump in `pyproject.toml` or `__init__.py`. Untagged builds get a local-version segment (`0.0.2.dev3+g<sha>`) which PyPI rejects, so accidental publishes from non-tagged commits aren't possible.

**Pre-releases.** Use PEP 440 suffixes: `v1.0.0a1`, `v1.0.0rc1`, etc. The `:latest` Docker tag is suppressed for any tag containing `rc`, `a`, or `b`.

**One-time setup** (already in place for this repo, here for reference):
- PyPI: Trusted Publisher pointing at `tmarkovski/dbos-argus` / workflow `release.yml` / environment `pypi`
- GitHub: repo secret `DOCKERHUB_TOKEN`; environment `pypi` (with optional required reviewers for an approval gate)

PyPI rejects re-uploading the same version, so each release must bump the version. If a publish fails partway (e.g. PyPI succeeded but Docker didn't), `gh run rerun <id> --failed` re-runs only the failed jobs.

## Principles

1. Argus is read-mostly. It only reads from DBOS Transact's `dbos.*` system tables. Future write actions (cancel, resume, fork) will go through DBOS Transact's own APIs from inside the Argus server process.
2. The console is a client. It talks only to the Argus backend, never to Postgres directly.
3. Boring is good. Prefer standard, well-documented libraries.

See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for community expectations.
