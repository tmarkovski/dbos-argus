#!/usr/bin/env bash
# Demo container entrypoint (Dockerfile.demo).
#
# Same process layout as scripts/replit-deploy.sh, but inside the demo image
# where everything is pip-installed onto PATH (no uv): run the Argus server in
# the foreground with the sample-app demo processes forked in the background,
# all against one ephemeral SQLite file. Worker output goes to stdout so
# platform log streaming shows the activity.

set -euo pipefail

DB_FILE="${ARGUS_DEMO_DB:-/tmp/argus-demo.sqlite}"
export ARGUS_DATABASE_URL="sqlite+aiosqlite:///${DB_FILE}"
export DBOS_SYSTEM_DATABASE_URL="sqlite:///${DB_FILE}"

# One-shot: run DBOS migrations and queue registration before any long-running
# process starts. Without this, the simulator/scheduler/metrics-runner race
# CREATE TABLE on a fresh SQLite file.
argus-runner prepare

argus-simulator &
SIM_PID=$!
argus-scheduler &
SCH_PID=$!
argus-metrics-runner &
MET_PID=$!

cleanup() {
  kill "${SIM_PID}" "${SCH_PID}" "${MET_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec dbos-argus --host 0.0.0.0 --port "${PORT:-8090}"
