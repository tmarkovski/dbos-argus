#!/usr/bin/env bash
# Replit deployment entrypoint.
#
# Runs the built Argus server (FastAPI serving the bundled SPA) in the
# foreground, with the sample-app demo processes forked in the background so
# the dashboard has live workflow activity to show. Backed by a SQLite file in
# /tmp — ephemeral, reset on every cold start, no external DB required.
#
# Mirrors `pnpm demo` (scripts/demo.mjs + tests/sample-app `demo` task) for the
# env / process layout, but uses the production `dbos-argus` CLI instead of
# Vite + uvicorn --reload.

set -euo pipefail

DB_FILE="${ARGUS_DEMO_DB:-/tmp/argus-demo.sqlite}"
export ARGUS_DATABASE_URL="sqlite+aiosqlite:///${DB_FILE}"
export DBOS_SYSTEM_DATABASE_URL="sqlite:///${DB_FILE}"

# One-shot: run DBOS migrations and queue registration before any long-running
# process starts. Without this, the simulator/scheduler/metrics-runner race
# CREATE TABLE on a fresh SQLite file.
uv run argus-runner prepare

uv run argus-simulator >/tmp/argus-simulator.log 2>&1 &
SIM_PID=$!
uv run argus-scheduler >/tmp/argus-scheduler.log 2>&1 &
SCH_PID=$!
uv run argus-metrics-runner >/tmp/argus-metrics-runner.log 2>&1 &
MET_PID=$!

cleanup() {
  kill "${SIM_PID}" "${SCH_PID}" "${MET_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec uv run dbos-argus --host 0.0.0.0 --port "${PORT:-5000}"
