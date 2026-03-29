#!/bin/bash
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
# recreate.sh — Recreate an existing site with improvements.
#
# Usage: ./recreate.sh <site_slug> <improvements_text>
#
# What it does:
#   1. Parses original build params (business name, niche, address, contact) from build.log
#   2. Rotates the current site folder to a versioned backup (sites/<slug>_v1, max 4)
#   3. Calls create.sh with the original params + SITE_IMPROVEMENTS injected into the prompt
#
# The site slug and site ID remain unchanged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SITE_SLUG="${1:-}"
IMPROVEMENTS="${2:-}"

# --- Validate args ---
if [ -z "$SITE_SLUG" ] || [ -z "$IMPROVEMENTS" ]; then
  echo "Usage: ./recreate.sh <site_slug> <improvements_text>" >&2
  exit 1
fi

if [ ! -d "$SCRIPT_DIR/sites/$SITE_SLUG" ]; then
  echo "ERROR: sites/$SITE_SLUG/ does not exist." >&2
  exit 1
fi

echo "═══════════════════════════════════════════════════"
echo "  ♻️   Site Recreation"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📁 Slug:         $SITE_SLUG"
echo "  📝 Improvements: ${IMPROVEMENTS:0:80}..."
echo ""

# --- Step 1: Parse original params from build.log (before rotating) ---
echo "🔍 Parsing original build parameters..."
PARAMS_OUTPUT=$("$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/scripts/version_backup.py" parse-params --slug "$SITE_SLUG" 2>&1)
if [ $? -ne 0 ]; then
  echo "ERROR: Could not parse build params:" >&2
  echo "$PARAMS_OUTPUT" >&2
  exit 1
fi
eval "$PARAMS_OUTPUT"

echo "  📂 Business: $BUSINESS_NAME"
echo "  🏷️  Niche:    $NICHE"
echo "  📍 Address:  $ADDRESS"
echo "  📞 Contact:  $CONTACT"
echo ""

# --- Step 2: Rotate backup (current → _v1) ---
echo "📦 Creating versioned backup..."
"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/scripts/version_backup.py" rotate --slug "$SITE_SLUG"
echo ""

# --- Step 3: Rebuild with improvements ---
echo "🔨 Starting rebuild with improvements..."
export SITE_IMPROVEMENTS="$IMPROVEMENTS"
exec "$SCRIPT_DIR/create.sh" "$BUSINESS_NAME" "$NICHE" "$ADDRESS" "$CONTACT"
