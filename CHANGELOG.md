# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

## [0.0.7] - 2026-04-29

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- Schema snapshot at `dbos_argus/data/dbos_schema.json` is now the *full*
  DBOS Postgres schema with per-column `"argus": true|false` markers
  (was a curated subset). Runtime diagnostics filter to argus-marked
  columns; the snapshot is also a complete reference of what DBOS ships.
- `GET /version` returns `tested_dbos_version` and `dbos-argus --version`
  prints `(tested against DBOS X.Y.Z)`, both sourced from the snapshot.
- `dbos-argus --dump-schema` flag connects, prints the live `dbos.*`
  schema as JSON, and exits — used to regenerate the snapshot from any
  DBOS database.
- Nightly `dbos-schema-watch` GitHub Action: pulls the latest DBOS from
  PyPI, bootstraps it in a Postgres service container, diffs against
  the snapshot, and opens an issue (idempotent on title) with a
  regenerated snapshot and a bucketed report ("Breaking for Argus" vs
  "Untracked DBOS changes") when anything changed. Manual `force` and
  `skip_issue` dispatch inputs available for debugging.

### Changed
- Generic `schema_dump` / `schema_diff` machinery — no DBOS-specific
  knowledge baked into the runtime.
- All JavaScript-based GitHub Actions bumped past the Node.js 20
  deprecation (checkout v6, setup-node v6, setup-uv v8, pnpm v5,
  docker/* latest).

## [0.0.6] - 2026-04-29

### Added
- `/api/sql-diagnostics` inspects the live `dbos` schema for the tables,
  columns, and column types Argus currently depends on, and reports missing
  objects and type mismatches directly to the console.
- The connection sidebar item now loads SQL diagnostics on app mount, caches
  the report in page state, and surfaces green/yellow/red connection states
  so legacy DBOS schema mismatches are visible without opening the sheet.

### Fixed
- Azure Database for PostgreSQL hosts now default to `sslmode=require` when no
  explicit `sslmode` is supplied, so pasted Azure connection strings work
  without adding TLS flags by hand.

## [0.0.5] - 2026-04-29

### Fixed
- `--db-url` now translates libpq-only query params that asyncpg rejects:
  `?options=-c<key>=<val> ...` is lifted into asyncpg's `server_settings`,
  and `?sslmode=...` becomes `ssl=...`. Previously these passed through to
  `asyncpg.connect()` and crashed with `TypeError: unexpected keyword
  argument 'options'` (common when copying connection strings from Azure
  Postgres Flex / Heroku that include a `search_path` override).

## [0.0.4] - 2026-04-29

### Fixed
- `--db-url` now accepts bare `postgresql://` and `postgres://` URLs; the
  scheme is rewritten to `postgresql+asyncpg://` so users can paste a standard
  libpq connection string without hitting `ModuleNotFoundError: psycopg2` from
  SQLAlchemy's default driver pick. Explicit driver suffixes are preserved.

## [0.0.3] - 2026-04-29

### Changed
- Console body uses the sidebar surface as its background so Safari 26 picks
  it up for the tinted toolbar at first paint.
- Notification details pane: stacked label-on-top/value-below fields,
  destination rendered as the parent→child workflow chain, sheet widened.
- App shell header rounding (`rounded-t-2xl`) aligns with the inset's outer
  corners — no more bottom-border showing through the curve.

### Fixed
- Sheet `max-width` overrides now actually apply: matched the base sheet's
  `data-[side=right]:sm:` variant so `tailwind-merge` dedupes the conflict.
- `/healthz` access-log spam silenced via a uvicorn access-log filter — the
  console polls it every 5s for the connection indicator.

## [0.0.2] - 2026-04-29

### Fixed
- Docker Hub `tmarkovski/dbos-argus:latest` image — pre-existing `uv sync` workspace
  resolution bug in the old multi-stage build had been silently failing on tag
  pushes. New single-stage `pip install dbos-argus` Dockerfile sidesteps it.

### Changed
- Release pipeline merged into one workflow with sequenced jobs
  (PyPI → Docker → GitHub Release). Docker waits for PyPI, no propagation race.
- `:edge` Docker tag retired in favor of `:latest`.

## [0.0.1] - 2026-04-29

### Added
- First public release of the `dbos-argus` package on PyPI.
- `dbos-argus` console script (click + uvicorn) — run with `uvx dbos-argus --db-url ...`.
- SvelteKit console SPA bundled inside the wheel at `dbos_argus/_console/`, served by FastAPI on the same port.
- Read-only views of DBOS Transact's `dbos.workflow_status`, `operation_outputs`, `workflow_schedules`, `notifications` system tables.
- Workflow detail page with parent/child family DFS view, step timelines, lazy-loaded outputs, and `DBOS.sleep` / `DBOS.setEvent` decoding.
- Single-stage Docker image at `tmarkovski/dbos-argus`, multi-arch (amd64/arm64), installed straight from PyPI.

[Unreleased]: https://github.com/tmarkovski/dbos-argus/compare/v0.0.7...HEAD
[0.0.7]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.7
[0.0.6]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.6
[0.0.5]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.5
[0.0.4]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.4
[0.0.3]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.3
[0.0.2]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.2
[0.0.1]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.1
