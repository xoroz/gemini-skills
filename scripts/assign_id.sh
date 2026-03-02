#!/bin/bash
# ============================================================================
# assign_id.sh — Manually assign a short ID to a business
# ============================================================================
#
# Usage:
#   ./scripts/assign_id.sh 00A "Marble Nails di Bertola Giada"
#
# What it does:
#   1. Registers the ID → business mapping in sites/site-id.json
#   2. Creates the redirect HTML file sites/<ID>.html (if site folder exists)
#   3. Prints the assigned ID and URLID
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ID_MANAGER="$SCRIPT_DIR/id_manager.py"

# Load .env for REMOTE_SITE_URL
if [ -f "$PROJECT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^\s*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    if [ -z "${!key+x}" ]; then
      export "$line" 2>/dev/null || true
    fi
  done < "$PROJECT_DIR/.env"
fi

REMOTE_SITE_URL="${REMOTE_SITE_URL:-}"
SITE_LANG="${SITE_LANG:-it}"

# --- Args ---
if [ $# -lt 2 ]; then
  echo "Usage: $0 <ID> <Business Name>"
  echo ""
  echo "Examples:"
  echo "  $0 00A \"Marble Nails di Bertola Giada\""
  echo "  $0 13B \"Estetica Lara\""
  echo ""
  echo "This assigns the given short ID to the business and creates"
  echo "the redirect HTML file in the sites/ directory."
  exit 1
fi

SITE_ID="$1"
BUSINESS_NAME="$2"

# Derive slug (same logic as create.sh)
SITE_SLUG=$(echo "$BUSINESS_NAME" | sed -e 's/ /-/g' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-' | sed -E 's/--+/-/g' | sed -E 's/^-|-$//g')

echo ""
echo "🆔 Assigning ID: $SITE_ID → $BUSINESS_NAME"
echo "   Slug: $SITE_SLUG"
echo ""

# Register in site-id.json
ID_OUTPUT=$(uv run "$ID_MANAGER" assign \
    --id "$SITE_ID" \
    --business "$BUSINESS_NAME" \
    --remote-url "${REMOTE_SITE_URL:-}" 2>&1)

ASSIGNED_ID=$(echo "$ID_OUTPUT" | grep '^SITE_ID=' | cut -d= -f2)
ASSIGNED_URLID=$(echo "$ID_OUTPUT" | grep '^URLID=' | cut -d= -f2)

if [ -z "$ASSIGNED_ID" ]; then
  echo "❌ Failed to assign ID. Output:"
  echo "$ID_OUTPUT"
  exit 1
fi

echo "   ✅ Registered: $ASSIGNED_ID"
echo "   🔗 URLID: $ASSIGNED_URLID"

# Create redirect HTML if site folder exists
SITE_DIR="$PROJECT_DIR/sites/$SITE_SLUG"
REDIRECT_FILE="$PROJECT_DIR/sites/${ASSIGNED_ID}.html"

if [ -d "$SITE_DIR" ]; then
  cat > "$REDIRECT_FILE" <<REDIRECT_EOF
<!DOCTYPE html>
<html lang="$SITE_LANG">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=${SITE_SLUG}/index.html">
<title>Redirect → $BUSINESS_NAME</title>
</head>
<body>
<p>Redirecting to <a href="${SITE_SLUG}/index.html">$BUSINESS_NAME</a>...</p>
</body>
</html>
REDIRECT_EOF
  echo "   📄 Redirect: sites/${ASSIGNED_ID}.html → $SITE_SLUG/index.html"
else
  echo "   ⚠️  Site folder '$SITE_DIR' does not exist yet."
  echo "      Redirect HTML will be created when the site is built."
  echo "      (Or run create.sh with SITE_ID=$ASSIGNED_ID)"
fi

echo ""
echo "Done! To use this ID with a new build:"
echo "  SITE_ID=$ASSIGNED_ID ./create.sh \"$BUSINESS_NAME\" \"niche\" \"address\" \"tel\""
echo ""
