#!/usr/bin/env bash
# Build the PyPI distribution for dbos-argus.
#
# Steps:
#   1. Build the SvelteKit console SPA.
#   2. Sync it into packages/server/dbos_argus/_console/ so hatch picks it up
#      as a wheel artifact.
#   3. Run `uv build` against packages/server, producing wheel + sdist.
#
# Output: dist/{dbos_argus-*-py3-none-any.whl, dbos_argus-*.tar.gz} (workspace-root dist/)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONSOLE_BUILD="apps/console/build"
PKG_CONSOLE_DIR="packages/server/dbos_argus/_console"

echo "==> Building console SPA"
pnpm --filter console build

if [ ! -d "$CONSOLE_BUILD" ] || [ ! -f "$CONSOLE_BUILD/index.html" ]; then
  echo "ERROR: $CONSOLE_BUILD missing or has no index.html — console build did not produce expected output." >&2
  exit 1
fi

echo "==> Syncing console build to $PKG_CONSOLE_DIR"
rm -rf "$PKG_CONSOLE_DIR"
mkdir -p "$PKG_CONSOLE_DIR"
cp -R "$CONSOLE_BUILD"/. "$PKG_CONSOLE_DIR/"

echo "==> Building wheel + sdist"
rm -rf dist
uv build packages/server

echo
echo "Built artifacts:"
ls -lh dist
