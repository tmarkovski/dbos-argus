# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.28] - 2026-06-09

> **Tested against DBOS 2.23.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Argus tracks the latest DBOS schema and does not aim for backward compatibility; the dependency floor is now `dbos>=2.23.0`. Pointing Argus at an older DBOS database whose `dbos.workflow_status` lacks `completed_at` will error on the workflow list / detail reads.

### Added
- Workflow **completion time**. DBOS 2.23.0 added `dbos.workflow_status.completed_at`,
  the canonical wall-clock timestamp for when a workflow reached a terminal
  state. Argus now reads it: it appears as `completed_at` on the workflow
  list and detail API/realtime payloads, and the workflow detail pane shows
  a **Completed** row and computes the workflow **Duration** from
  `started_at → completed_at` (falling back to `updated_at` while still
  running). Null for workflows that haven't finished.

### Changed
- Schema snapshot regenerated against DBOS 2.23.0 (closes the `dbos-watch`
  drift issue). `workflow_status.completed_at` is now argus-tracked.
- Bumped the `dbos` dependency floor to `>=2.23.0` to align Argus with the
  DBOS release that introduced `completed_at`.

## [0.0.27] - 2026-05-09

> **Tested against DBOS 2.21.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- New top-level **Queues** page surfacing the persisted DBOS queue registry
  (`dbos.queues`, added in DBOS 2.21). Shows each queue's concurrency,
  worker concurrency, rate limit, priority/partition flags, and last-updated
  timestamp. Empty / never-used queues now appear here even before any
  workflow has been enqueued onto them. Each row links to the existing
  workflows view filtered by queue name.
- Queues page now shows live `Enqueued` and `Running` counts per queue,
  joined from `workflow_status` against the queue name in a single
  aggregate query. Each non-zero count links straight to the workflows
  list filtered by queue + status.
- New `GET /api/queues` REST endpoint and matching `queues` realtime
  channel — same payload shape on both transports.
- Sidebar connection footer now reports the actual backend (PostgreSQL or
  SQLite) plus its server version, replacing the previous hard-coded
  "Read-only DBOS Postgres" label. `/healthz` and the `health` realtime
  channel both expose the new `database_dialect` and `database_version`
  fields.
- Dashboard **top-queues card** replaces the old "DBOS queue registry"
  tile: shows the top three queues by `enqueued + running` as horizontal
  bars (chart-3 / chart-2 / chart-1 fills against a track that adapts to
  the active theme), each linking to the workflows list filtered by that
  queue plus the ENQUEUED + PENDING statuses. Inactive queues stay in
  the list with zero-width fills so the card doesn't collapse on quiet
  databases. The registered-queue total moved to the layers badge in
  the top-right corner.

### Changed
- Schema snapshot regenerated against DBOS 2.21.0. `dbos.queues` is now
  argus-tracked across all 11 columns; `workflow_status.rate_limited` is
  recorded as untracked (it's DBOS-internal accounting, not a user-facing
  signal — every workflow run from a rate-limited queue gets the flag set,
  not just throttled ones).
- Dashboard **KPI cards are now click-through**: an absolutely-positioned
  anchor stretches over each card so the entire surface routes to the
  relevant page (`/workflows/`, `/notifications/`, `/schedules/`,
  `/queues/`), with internal anchors (per-status badges, the
  failed-recent link, per-queue bars) lifted above via `relative z-10`
  so deep links still reach the right filtered view. Cursor is
  `pointer` over the whole card and a hover shadow + ring strengthens
  the affordance.
- **Sidebar wrapper** now darker than the inset surface in both themes
  — the preset's `--sidebar` token sat at ~white in light mode and was
  lighter than the inset in dark mode, so the rounded inset panel had
  no visible frame in either theme. Override pulls light-mode sidebar
  to `oklch(0.94)` (vs `1.0` background) and dark-mode sidebar to
  `oklch(0.10)` (vs `0.145` background) so the inset reads as a lifted
  panel against a darker frame.

## [0.0.26] - 2026-05-06

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- Result pane: lightweight, dependency-free JSON syntax highlighter
  (`JsonView`). Tries `JSON.parse` first; on success, tokenizes via the
  classic Crockford regex and colors keys / strings / numbers / booleans /
  null using existing theme tokens (keys use `--workflow-accent` so they
  brighten against dark muted surfaces, the same treatment workflow-graph
  child names already use). Falls back to escaped plain text when the
  payload isn't parseable JSON (raw base64, malformed strings) so the
  box still renders the value.

### Changed
- Result pane (output dialog): the bordered code box itself is now the
  scroll container instead of the wrapper around it. Wrapper switched
  to a `flex flex-col` slot and the box gets `min-h-0 flex-1
  overflow-auto`, so the border stays pinned at the dialog's bounds
  while long JSON scrolls inside.
- Result pane (side panel): output box capped at `max-h-[70vh]` with
  `min-h-64`. Long JSON now scrolls within the box up to ~70% of the
  viewport instead of stretching the side pane down to match the
  payload, while keeping a sensible minimum so the box stays usable
  when metadata above it grows or the window shrinks.

## [0.0.25] - 2026-05-06

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Fixed
- Pickle decoder now survives REDUCE-path calls to unknown classes
  (e.g. a timezone-aware `datetime` whose `tzinfo` reduces to
  `datetime.timezone(timedelta(0))`). Previously the opaque proxy
  rejected positional args from REDUCE and aborted the entire decode
  with `TypeError: ...timedelta() takes no arguments`, leaving real
  step outputs as a raw base64 blob in the UI.
- Allowlisted common stdlib value types — `datetime.{datetime,date,time,
  timedelta,timezone}`, `decimal.Decimal`, `uuid.UUID` — so they decode
  to native Python and the JSON encoder renders them as ISO 8601 strings
  / decimal strings instead of opaque dicts.

## [0.0.24] - 2026-05-06

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Pickle decoder now renders unknown classes (Pydantic `BaseModel`,
  dataclasses, plain Python objects) as `{"__class__": "module.Name",
  ...fields}` instead of falling back to the raw base64 blob. The
  unpickler swaps unknown classes for an inert `_OpaqueObject` proxy that
  captures BUILD state via `__setstate__` — the user's module is never
  imported and no user code runs, so the existing safety guarantee
  holds (covered by a regression test that constructs a pickle stream
  resolving `os.system` and verifies it doesn't execute). Pydantic v2's
  envelope state (`__pydantic_fields_set__` / `__pydantic_extra__` /
  `__pydantic_private__`) is stripped so the UI sees just the model's
  real fields.
- README: `uvx dbos-argus` examples now use `dbos-argus@latest` so each
  invocation re-resolves the version instead of reusing the wheel `uvx`
  cached the first time.

## [0.0.23] - 2026-05-06

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Fixed
- Bundled console no longer hits a `403 Forbidden` on the `/ws` upgrade.
  `ARGUS_CORS_ORIGINS` now defaults to `*` instead of the Vite dev port,
  so the SPA served by FastAPI works on any listen port (and any custom
  Vite dev port works without extra config). Argus is an unauthenticated
  read-only dev tool typically bound to localhost — operators who expose
  it more widely should narrow `ARGUS_CORS_ORIGINS` to their console
  origin(s).

### Changed
- README: documented SQLite as a first-class backend alongside Postgres,
  with `uvx` / `pipx` / Docker examples for both, the four-slash absolute
  path convention for `sqlite://` URLs, and an updated architecture
  diagram showing the dual-backend store.

## [0.0.22] - 2026-05-05

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Default preset switched to `b5TiUdXFtA` (violet primary, neutral charts,
  Inter sans + Roboto Slab heading) via `pnpm --filter console theme:sync`.
  Favicon set (svg + 16/32 + apple-touch) recolored from the prior teal
  `#00786f` to violet `#6d28d9` to match the new `--primary`.
- Workflow detail flow: step pills lost their gray fill in favor of a
  transparent rounded-full border. Hover gets a faint `bg-muted/40` tint;
  selected state swaps to a `border-primary` outline with a `bg-primary/5`
  inset. Workflow containers lost their drop shadows in all three states
  (selected / current / default) — the borders alone carry the structure
  now that the step layer is quieter.
- Workflow detail flow, awaited and spawn rows: the directional arrow
  (`←` for `DBOS.getResult`, `→` for child spawn) moved out of the step
  body and onto the duration line on the right, so it visually anchors
  at the same edge of the pill as the spawn / return xyflow handles.
  Awaited rows dropped the literal "result" prefix; both rows show the
  cross-workflow target name in the body slot, and child rows resolve
  the spawned workflow's display name via family lookup (paralleling
  the existing awaited-name resolution).
- Workflow detail side pane: title bar now reads "Workflow details" /
  "Step #N details" (was "... result") since the pane carries metadata
  + events alongside the result. New collapse toggle in the eyebrow
  (`PanelRightClose` / `PanelRightOpen` via the same `icon-sm` ghost
  Button as the layout's sidebar trigger and theme switcher) hides the
  body and animates the pane width down to a 64px peek. The resize
  handle stays in place; grabbing it while collapsed pulls the pane
  out of the peek under the cursor instead of jumping to the saved
  expanded width, and releasing below the usable minimum snaps back
  to collapsed.

## [0.0.21] - 2026-05-04

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- SQLite backend support via the new `ArgusDB` adapter split. Point
  `ARGUS_DATABASE_URL` at `sqlite+aiosqlite:///path/to/argus.db` and
  the entire stack (REST + realtime) works against the DBOS app's
  SQLite store. CI matrix runs the test suite against both backends.
- Realtime (WebSocket) layer at `/ws` replaces per-page polling. One
  multiplexed socket carries every page's subscriptions; server-side
  pollers gate heavier snapshots behind a cheap cursor query and shut
  down when the last subscriber disconnects. Channels: `health`,
  `stats`, `stats.timeseries`, `workflows`, `workflow`, `schedules`,
  `notifications` — each emits the same JSON shape as its REST
  counterpart, which remains authoritative for curl/debug. Cursor
  queries are implemented per-dialect on `ArgusDB` so the layer works
  unchanged on both Postgres and SQLite. Configurable via
  `ARGUS_REALTIME_ENABLED`, `ARGUS_REALTIME_INTERVAL_MS`,
  `ARGUS_REALTIME_HEALTH_INTERVAL_MS`, and
  `ARGUS_REALTIME_MAX_SUBS_PER_CONN`.
- Live workflow detail page: subscribing to `workflow` with `{id}`
  re-snapshots every tick so steps appear as they complete.

### Changed
- Connection indicator now reflects WebSocket health (with a 1Hz
  poll surfacing disconnects as a sticky `fetchError`) instead of
  per-page `setInterval(5000)` `/healthz` fetches. While diagnostics
  report issues (e.g. dbos schema absent), the indicator re-polls
  `/api/sql-diagnostics` every 5s so it converges automatically once
  the DBOS app provisions its tables — no hard refresh needed.
- Hub suppresses `update` broadcasts when a fresh snapshot is
  byte-identical to the cached one. Cursor-less channels (`workflow`,
  `health`) re-snapshot every tick; the dedupe keeps the wire quiet
  and prevents xyflow edge-dash animations on the workflow detail
  page from restarting on every poll.

### Fixed
- Workflow flow renders the container header (name + ID) for
  freshly-spawned workflows that have no steps yet — ELK was
  collapsing empty containers to ~0×0, leaving only the status
  badge visible until the first step landed.

## [0.0.20] - 2026-05-04

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

> **Note:** v0.0.19 was published to PyPI but the docker/release jobs
> in the release pipeline failed — `pip install dbos-argus==0.0.19`
> inside the Dockerfile raced PyPI's CDN propagation on the arm64
> runner and died with "No matching distribution found", which then
> cancelled the rest of the matrix. v0.0.20 carries the same intended
> changes plus the pipeline fix, so the Docker image and GitHub
> Release exist for this tag.

### Fixed
- Release pipeline: each `docker-build` arch now polls PyPI's simple
  index for the freshly published version (via `pip download --no-deps`,
  60 attempts × 5s) before invoking buildx, so a wheel that hasn't yet
  propagated to every Fastly edge can no longer race the in-Dockerfile
  `pip install`.

## [0.0.19] - 2026-05-04

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Workflow list filters now persist across reloads. Search query,
  date range, and selected status set are written to localStorage
  alongside the existing hide-scheduled and enqueued-collapsed keys
  (`argus.workflows.q`, `argus.workflows.dateRange`,
  `argus.workflows.statuses`). Hydration runs at script init (the
  console is `ssr = false`) so the first fetch already includes the
  persisted search instead of waiting one debounce tick. Default
  values are removed from storage rather than written, so a fresh
  install with no prior key matches the post–"Clear filters" state.

## [0.0.18] - 2026-05-03

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Workflow detail flow: child-step Workflow icon, child step name,
  awaited-name in `result ← <child>`, and the spawn / default-return
  edges all moved off `--chart-3` and onto a new
  `--workflow-accent` token. The token tracks `--primary` in light
  mode, and in dark mode lifts L to `0.82` and bumps chroma by
  `+0.06` via relative-color syntax (`oklch(from var(--primary) ...)`)
  so presets that pick a deep primary (current teal is L=0.437)
  still read as a clear accent against the dark card. Error /
  cancelled return edges keep their `--status-error` /
  `--status-warning` strokes.
- Workflow detail flow: ambient gradient gained a third point at
  bottom-left (`--color-chart-2`, 12% mix), so the canvas reads as
  a balanced three-corner wash instead of a single diagonal sweep.

## [0.0.17] - 2026-05-03

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Dashboard **workflow throughput chart** switched from stacked area to
  stacked bar (layerchart `BarChart` with `seriesLayout="stack"`,
  `bars: { strokeWidth: 0 }` to drop the segment outlines). 30-day
  range tick count capped at 6 so day labels no longer overlap.
- Sidebar nav badges: when a multi-category item (Workflows: Running +
  Queued) has only one non-zero count, it still renders the labeled
  sub-row instead of collapsing to an unlabeled single pill, so the
  category is unambiguous. Single-category items (Notifications) keep
  the right-aligned single pill.
- Default preset switched to `b5XSmcsWXI` (teal primary, Inter sans +
  Roboto Slab heading) via `pnpm --filter console theme:sync`.
- Console favicon: white-eye-on-teal-circle generated from the same
  Lucide glyph as the brand mark — shipped as `favicon.svg`, plus
  rasterized `favicon-16.png` / `favicon-32.png` (Safari prefers PNG
  for tab favicons and trips a contrast-tile heuristic on some SVGs)
  and an `apple-touch-icon.png` (180×180) for iOS / Safari Start Page.

### Added
- Sample app gained a fourth process: `argus-heartbeat-runner`. The
  scheduled `heartbeat_check` workflow is now registered with
  `queue_name="argus-heartbeats"`, so each tick **enqueues** a
  workflow row instead of running it locally. The new runner
  subscribes as a worker for that queue and executes the body — run
  zero, one, or many of them. Lets you watch heartbeats accumulate
  in `ENQUEUED` (with no runner) or distribute the work (with
  several). `argus-scheduler` declares the queue with
  `worker_concurrency=0` so the scheduler never dequeues its own
  ticks. Migration logic in `register_schedules()` rewrites
  pre-existing un-queued schedule rows on first launch.

## [0.0.16] - 2026-05-02

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Console theme split into a generated `theme.css` (preset-controlled
  palette/fonts/radius) and a hand-maintained `app.css` (Argus-specific
  status/highlight/mono tokens). Swapping shadcn presets is now
  `pnpm --filter console theme:sync <code>` plus a font-package update,
  with no merging of token blocks. Documented in `CLAUDE.md` →
  *Theming*. Default preset switched to `b4b3RGTOyW` (olive base,
  yellow primary, sky charts, DM Sans + Merriweather, large radius).
- All hardcoded palette classes swept for preset compatibility:
  workflow status badges/dots route through `--status-*` tokens,
  search highlights and the event-icon use `--highlight*`, and the
  Argus eye logo picks up `--primary`. Status badges now display in
  Title case via a shared `formatStatus()` helper that consults
  `STATUS_LABELS` (`MAX_RECOVERY_ATTEMPTS_EXCEEDED` → `Max retries`).
- Workflow detail flow: ambient gradient and spawn/return edges now
  draw from `--color-chart-1` / `--color-chart-3` / `--color-chart-5`
  so they track the active preset; child-workflow steps render the
  Lucide `Workflow` icon (instead of a plain dot) tinted with
  `text-chart-3`. Error/cancelled return edges moved to
  `--status-error` / `--status-warning`.
- Dashboard "Connected" indicator now uses `font-heading`, matching
  the other card titles.
- App shell: the children container clips to `md:rounded-b-2xl` so
  the bottom corners follow the inset's curve without breaking the
  sticky header.

## [0.0.15] - 2026-05-02

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Developer experience
- Added a `.pre-commit-config.yaml` running `ruff-check --fix` and
  `ruff-format` on staged files (pinned to ruff 0.15.11). Contributors
  enable it once with `uvx pre-commit install`; CONTRIBUTING.md
  documents the step.

## [0.0.14] - 2026-05-02

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- Sidebar nav badges driven by a shared `statsState` store (single
  `/api/stats` poll, also consumed by the home page so there's no
  duplicate polling). The Workflows item shows Running and Queued
  sub-rows with colored count pills; the Notifications item shows a
  single Pending pill on the right.

### Changed
- Workflow detail flow: container nodes are fully opaque (`bg-card`,
  no backdrop blur) so the ambient gradient sits behind the cards
  instead of bleeding through them. Pill-shaped step nodes, straight
  sequential edges, hidden handles, thicker spawn/return edges, soft
  indigo/violet radial gradient on the flow surface, rounder
  workflow containers with border-color + shadow elevation in place
  of the ring glow.
- Workflows list: the enqueued strip header now reads the true total
  from `/api/stats` when not scoped to a single queue, so it no
  longer caps at the rendered row limit.
- Sidebar: dropped the redundant "Navigation" group label; the Argus
  eye logo is now fully circular.
- Workflow list filter toolbar: Hide-scheduled and Clear-filters now
  match the outline-pill styling of the other filters (FilterX icon
  on Clear), and the search input is hardened against Safari contact
  autofill.

## [0.0.13] - 2026-05-02

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Added
- Workflows list: when the enqueued strip is expanded, render table
  headers (Queue / Prio / Name / Workflow ID / Enqueued), surface the
  DBOS queue **priority** column (lower runs first), and tag
  cron-scheduled workflows with a calendar-clock glyph next to the
  name (detected via the `sched-` workflow_uuid prefix).
- Dashboard: total-workflows card now shows the queued count next
  to the in-flight count.

### Changed
- Result pane: aligned the output dialog with the event dialog —
  step name as title with `Step #N` description, OUTPUT label inline
  with the action row, matching gap between buttons and code block.
  Side-pane output area is fully clickable and both the event cards
  and the output code block fade in a colored hover border to
  signal they're reactive.
- Result pane: event dialog now uses the same View Transitions
  morph as the output dialog — cards morph into the dialog on open
  and back on close, with the same Safari close-side skip.
- Event dialog text: `Set once` / `Set N times` are now `Event set
  once` / `Event set N times` so the source is unambiguous.
- Dashboard: connected indicator is now a plug-zap icon (paired
  with the existing unplug for disconnected) instead of a checkmark.
- Workflow detail flow: dropped the dotted xyflow background for a
  clean pane.

### Schema
- `dbos.workflow_status.priority` flipped from `argus: false` to
  `argus: true` (now read by the workflows list endpoint).

## [0.0.12] - 2026-04-30

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

> **Note:** v0.0.11 was tagged but never published — the release pipeline's
> "Build wheel + sdist" step OOMed on the GitHub runner during the SvelteKit
> SPA build (Vite hit Node's default ~2 GB heap mid-rollup). v0.0.12 carries
> the same intended changes plus the build fix.

### Added
- Dashboard **workflow throughput chart**: stacked-area view (succeeded /
  errored / running) backed by a new `GET /api/stats/timeseries?range=`
  endpoint. Range toggles between last 24h (hourly buckets), 7 days, and
  30 days (daily buckets). Buckets are filled densely via `date_trunc` +
  `generate_series` so empty windows render correctly. Polls every 10s.
- Workflow detail: an **expand-to-dialog** button on the result pane,
  morphing the output box into a full-screen dialog via the View
  Transitions API for the JSON output of step/workflow records.

### Changed
- Dashboard layout: throughput chart and the recent-workflows table sit
  side-by-side at `@5xl/main` (≈1024px), stacked single-column below.
  Recent workflows columns reordered to **Status / Name / Started /
  Workflow ID**, with the Workflow ID column truncating to fit the
  shared width.
- Workflow detail pane: tinted hover on the Database tile and more
  workflow metadata surfaced in the detail summary.
- ResultPane: skip the view-transition close morph on Safari (the
  reverse direction stutters in Safari 26's WebKit, expand still
  morphs).
- Repo README: refreshed hero — dashboard + workflow graph screenshots
  above the fold, workflows list lower down. Localhost URL surfaced
  before the runner options. Dropped stale "must use `+asyncpg://`
  prefix" gotcha (auto-rewritten since 0.0.4).
- PyPI README: rewrote install/run instructions around the actual CLI
  (`uvx dbos-argus --db-url ...`, `pipx`, Docker) instead of the old
  `uv add` / `uvicorn` invocations, plus inline screenshots from
  `raw.githubusercontent.com`.

### Fixed
- Release pipeline: bumped `NODE_OPTIONS=--max-old-space-size=4096` for
  the SPA build step in `release.yml` and `ci-node.yml`. Vite's dual
  SSR + client rollup transforms ~11.7k modules each and was OOMing
  against Node's default 2 GB old-space heap.

## [0.0.10] - 2026-04-29

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Dashboard top row: replaced the standalone "In flight" tile with a
  clickable **Database** tile at the start of the row. State is conveyed
  via a colored title and Lucide icon (`circle-check` /
  `circle-alert` / `unplug`) for Connected / Incompatible schema /
  Not connected; clicking the tile opens the same SQL-diagnostics sheet
  the sidebar footer uses. The in-flight count remains as the corner
  badge on Total workflows.
- Connection health, SQL diagnostics, and sheet-open state moved to a
  shared `connectionState` module so the diagnostics survive client-side
  navigation. Previously they were stored in `page.state`, which resets
  per history entry — the indicator briefly went green after navigating
  away from the home page.
- Top-row card gradient switched from `from-primary/5` to
  `from-foreground/5`, restoring the neutral-gray look from the shadcn
  blocks reference (`--primary` in this theme is brand-purple, which was
  tinting all four tiles).
- The dashboard's page-level fetch-error banner now hides while the
  database is not in a healthy connected state — the Database tile
  already surfaces the same condition.
- Release pipeline: docker step split into a parallel matrix
  (`docker-build` on native amd64 + native arm64 runners) plus a
  `docker-manifest` job that assembles the multi-arch image from the
  per-arch digests. Removes QEMU emulation, where arm64 was ~10× slower
  than amd64 (95s vs 10s for `pip install` alone).

## [0.0.9] - 2026-04-29

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

### Changed
- Reframe project positioning as a self-hosted, read-only **workflow viewer**
  for DBOS Transact rather than a "management console". Explicit guidance
  added pointing at DBOS Conductor for production workflow operations
  (recovery, retention, alerting, etc.). Updated package descriptions,
  READMEs, FastAPI app metadata, and architecture docs accordingly.
- Architecture invariant #1 changed from "Argus is read-mostly today" to
  "Argus is read-only" — reflecting the scope decision rather than a
  not-yet-implemented intervention API.

## [0.0.8] - 2026-04-29

> **Tested against DBOS 2.19.0** — see `tested_dbos_version` in `GET /version` and `dbos-argus --version`. Other DBOS versions may still work; the in-app connection indicator surfaces any schema mismatches.

> **Note:** v0.0.7 was tagged but never published — the release pipeline failed
> before reaching PyPI because `astral-sh/setup-uv@v8` is not a moving major
> tag (setup-uv stopped publishing those for supply-chain reasons in 8.0.0).
> v0.0.8 carries the same intended changes plus the workflow fix.

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

[Unreleased]: https://github.com/tmarkovski/dbos-argus/compare/v0.0.28...HEAD
[0.0.28]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.28
[0.0.27]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.27
[0.0.26]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.26
[0.0.22]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.22
[0.0.21]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.21
[0.0.20]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.20
[0.0.19]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.19
[0.0.18]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.18
[0.0.17]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.17
[0.0.16]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.16
[0.0.15]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.15
[0.0.14]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.14
[0.0.13]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.13
[0.0.12]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.12
[0.0.10]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.10
[0.0.9]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.9
[0.0.8]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.8
[0.0.6]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.6
[0.0.5]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.5
[0.0.4]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.4
[0.0.3]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.3
[0.0.2]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.2
[0.0.1]: https://github.com/tmarkovski/dbos-argus/releases/tag/v0.0.1
