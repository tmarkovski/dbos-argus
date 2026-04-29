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

## Schema snapshot (`expected_schema.json`)

The `/api/sql-diagnostics` endpoint compares the live `dbos.*` schema against a checked-in snapshot at `packages/server/dbos_argus/data/expected_schema.json`. The snapshot lists every table and column Argus reads — generic dump-vs-dump diff lives in `schema_diff.py` and has no DBOS-specific knowledge baked in.

**Regenerate when:**
- Bumping the `dbos` pin in `tests/sample-app/pyproject.toml` (or otherwise pulling a newer DBOS) and the new version adds/renames/retypes columns or tables Argus uses.
- Adding a new query in `packages/server/dbos_argus/main.py` that touches a column not currently listed in the snapshot.
- A user reports a false-positive "schema issue" on a current DBOS install (means the snapshot has drifted from reality).

**How to regenerate:**

```bash
# 1. Stand up a fresh DBOS app against a clean Postgres so DBOS bootstraps its
#    current schema (the sample-app fixture works):
docker compose up -d postgres
uv run argus-runner   # bootstraps dbos.* schema, then idle is fine — Ctrl+C

# 2. Dump the live schema and overwrite the snapshot:
uv run dbos-argus \
  --db-url 'postgresql+asyncpg://argus:argus@localhost:5432/argus' \
  --dump-schema \
  > packages/server/dbos_argus/data/expected_schema.json.full

# 3. Hand-edit the dump to keep only the tables/columns Argus actually reads
#    (the existing snapshot is the reference for the right scope). The dump
#    command emits everything in the schema; the checked-in file is the
#    minimal subset we depend on.
$EDITOR packages/server/dbos_argus/data/expected_schema.json.full
mv packages/server/dbos_argus/data/expected_schema.json{.full,}

# 4. Verify:
uv run pytest packages/server/tests/test_sql_diagnostics.py
curl -s http://localhost:8090/api/sql-diagnostics   # should be {"ok":true,"issues":[]}
```

The snapshot is intentionally curated, not a full pg_dump — the diff is one-sided (extra tables/columns in the live DB are ignored), so the snapshot is a "what we depend on", not "what DBOS currently ships". When in doubt, leave a column out: that just means we don't validate it.

## Releasing

Releases are tag-driven — pushing a `v*` tag fires `.github/workflows/release.yml`, which publishes to PyPI, builds and pushes the multi-arch Docker image, and creates the GitHub Release.

```bash
# 1. Move the [Unreleased] entries in CHANGELOG.md into a new
#    `## [X.Y.Z] - YYYY-MM-DD` section, and add the link reference at the bottom.
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
