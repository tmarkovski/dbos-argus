#!/usr/bin/env bash
# Regenerate apps/console/src/theme.css from a shadcn preset code.
#
# Usage:
#   pnpm --filter console theme:sync <preset-code>
#   ./scripts/sync-theme.sh <preset-code>
#
# Get a preset code from https://ui.shadcn.com/create — the URL ends with
# ?preset=<code>. The script:
#   1. Decodes the preset to show what changed
#   2. Spawns a scratch Next.js project (the React shadcn CLI requires one)
#   3. Runs `shadcn apply --preset <code> --only theme` to extract the CSS
#   4. Copies the :root and .dark blocks into src/theme.css with a header
#   5. Prints the @fontsource packages to install/uninstall manually
#
# Font @import lines in app.css are NOT auto-updated — review the suggested
# package changes printed at the end and run `pnpm --filter console add/remove`
# yourself, then update the @fontsource imports in app.css to match.

set -euo pipefail

CODE="${1:-}"
if [ -z "$CODE" ]; then
  echo "usage: $0 <preset-code>" >&2
  echo "  get a preset code from https://ui.shadcn.com/create" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CONSOLE_SRC="$REPO_ROOT/apps/console/src"
TARGET="$CONSOLE_SRC/theme.css"

DECODE="$(npx -y shadcn@latest preset decode "$CODE")"
echo "$DECODE"
echo

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

mkdir -p "$SCRATCH/src" "$SCRATCH/app"
cat > "$SCRATCH/package.json" <<'EOF'
{"name":"theme-extract","version":"0.0.0","dependencies":{"next":"^14.0.0","react":"^18.0.0","react-dom":"^18.0.0","tailwindcss":"^4.0.0"}}
EOF
cat > "$SCRATCH/components.json" <<'EOF'
{"$schema":"https://ui.shadcn.com/schema.json","style":"new-york","rsc":false,"tsx":true,"tailwind":{"config":"","css":"src/app.css","baseColor":"neutral","cssVariables":true,"prefix":""},"aliases":{"components":"@/components","utils":"@/lib/utils","ui":"@/components/ui","lib":"@/lib","hooks":"@/hooks"},"iconLibrary":"lucide"}
EOF
cat > "$SCRATCH/tsconfig.json" <<'EOF'
{"compilerOptions":{"baseUrl":".","paths":{"@/*":["./*"]}}}
EOF
echo '// placeholder' > "$SCRATCH/next.config.js"
cat > "$SCRATCH/app/layout.tsx" <<'EOF'
export default function L({children}:{children:any}){return <>{children}</>}
EOF
echo '@import "tailwindcss";' > "$SCRATCH/src/app.css"

npx -y shadcn@latest apply --preset "$CODE" --only theme -y -c "$SCRATCH" >/dev/null

# Pull just the :root and .dark blocks (preset apply only writes those).
EXTRACTED="$(awk '/^:root \{/,/^\}$/; /^\.dark \{/,/^\}$/' "$SCRATCH/src/app.css")"

# Inject --font-sans / --font-heading inside the :root block. The preset's
# CSS doesn't carry font tokens; the decode does. We append them so theme.css
# fully owns the fonts.
FONT_SLUG="$(echo "$DECODE" | awk '/^[[:space:]]+font[[:space:]]/{print $2}')"
FONT_HEADING_SLUG="$(echo "$DECODE" | awk '/^[[:space:]]+fontHeading[[:space:]]/{print $2}')"
FONT_FAMILY="$(echo "$FONT_SLUG" | awk '{
  n = split($0, parts, "-")
  out = ""
  for (i = 1; i <= n; i++) out = out (i>1 ? " " : "") toupper(substr(parts[i],1,1)) substr(parts[i],2)
  print out
}')"
FONT_HEADING_FAMILY="$(echo "$FONT_HEADING_SLUG" | awk '{
  n = split($0, parts, "-")
  out = ""
  for (i = 1; i <= n; i++) out = out (i>1 ? " " : "") toupper(substr(parts[i],1,1)) substr(parts[i],2)
  print out
}')"

EXTRACTED_WITH_FONTS="$(echo "$EXTRACTED" | awk -v fs="  --font-sans: '${FONT_FAMILY} Variable', sans-serif;" -v fh="  --font-heading: '${FONT_HEADING_FAMILY} Variable', serif;" '
  /^:root \{/ { in_root = 1; print; next }
  in_root && /^\}$/ { print fs; print fh; print; in_root = 0; next }
  { print }
')"

URL="https://ui.shadcn.com/create?preset=${CODE}"

{
  echo "/*"
  echo " * Theme generated from shadcn preset $CODE."
  echo " *"
  echo "$DECODE" | sed 's/^Preset/ * Preset/; t; s/^/ * /'
  echo " *"
  echo " * Do not edit by hand — regenerate with:"
  echo " *   pnpm --filter console theme:sync <preset-code>"
  echo " *"
  echo " * Argus-specific tokens (--status-*, --highlight*, --font-mono) live in"
  echo " * app.css and are unaffected by preset swaps."
  echo " */"
  echo
  echo "$EXTRACTED_WITH_FONTS"
} > "$TARGET"

echo "Wrote $TARGET"
echo
echo "Next steps:"
echo "  1. Update font imports in apps/console/src/app.css to match:"
echo "       @import \"@fontsource-variable/${FONT_SLUG}\";"
echo "       @import \"@fontsource-variable/${FONT_HEADING_SLUG}\";"
echo "  2. Install/uninstall fontsource packages:"
echo "       pnpm --filter console add @fontsource-variable/${FONT_SLUG} @fontsource-variable/${FONT_HEADING_SLUG}"
echo "       (remove the previous fonts if no longer used)"
echo "  3. Verify: pnpm run lint && pnpm run build"
