#!/bin/bash
# =============================================================================
# TexNGo Flyer Stamper
#
# Generates a personalised flyer by placing a QR code on the existing
# template image (assets/template-flyer.png).
#
# Usage:
#   ./create_assets.sh "Business Name" "https://preview-url.texngo.it"
#
# Output:
#   assets/flyers/flyer-<slug>.png          (always)
#   sites/<slug>/flyer-<slug>.png           (only if sites/<slug>/ exists)
#
# Examples:
#   ./create_assets.sh "Marble Nails di Bertola Giada" "https://marble-nails-di-bertola-giada.texngo.it"
#   ./create_assets.sh "Ristorante Da Mario" "https://ristorante-da-mario.texngo.it"
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"

MAKE_FLYER="$SCRIPT_DIR/scripts/make_flyer.py"
TEMPLATE="$SCRIPT_DIR/assets/template-flyer.png"

# =============================================================================
# INPUTS
# =============================================================================
BUSINESS_NAME="${1:-}"
PREVIEW_URL="${2:-}"

if [ -z "$BUSINESS_NAME" ] || [ -z "$PREVIEW_URL" ]; then
  echo ""
  echo "  Usage: ./create_assets.sh \"Business Name\" \"Preview URL\""
  echo ""
  echo "  Examples:"
  echo "    ./create_assets.sh \"Marble Nails di Bertola Giada\" \"https://marble-nails-di-bertola-giada.texngo.it\""
  echo "    ./create_assets.sh \"Ristorante Da Mario\"           \"https://ristorante-da-mario.texngo.it\""
  echo ""
  exit 1
fi

# Sanity checks
if [ ! -f "$TEMPLATE" ]; then
  echo "❌  Template not found: $TEMPLATE"
  exit 1
fi
if [ ! -f "$MAKE_FLYER" ]; then
  echo "❌  Flyer script not found: $MAKE_FLYER"
  exit 1
fi

# =============================================================================
# SLUG  (lowercase, hyphens, alphanumeric only — mirrors create.sh convention)
# =============================================================================
SLUG=$(echo "$BUSINESS_NAME" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/ /-/g' \
  | tr -cd '[:alnum:]-')

FLYER_NAME="flyer-${SLUG}.png"

# =============================================================================
# OUTPUT PATHS
# =============================================================================
ASSETS_FLYERS_DIR="$SCRIPT_DIR/assets/flyers"
ASSETS_OUTPUT="$ASSETS_FLYERS_DIR/$FLYER_NAME"

SITE_DIR="$SCRIPT_DIR/sites/$SLUG"
SITE_OUTPUT="$SITE_DIR/$FLYER_NAME"

mkdir -p "$ASSETS_FLYERS_DIR"

# =============================================================================
# BANNER
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════"
echo "  🎨  TexNGo Flyer Stamper"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📂  Client  : $BUSINESS_NAME"
echo "  🌐  URL     : $PREVIEW_URL"
echo "  🔑  Slug    : $SLUG"
echo ""
echo "  📁  Template: $TEMPLATE"
echo "  📁  Output  : $ASSETS_OUTPUT"
if [ -d "$SITE_DIR" ]; then
  echo "  📁  Site    : $SITE_OUTPUT"
fi
echo ""
echo "  ⏱️   Started : $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════"
echo ""

# =============================================================================
# GENERATE
# =============================================================================
uv run "$MAKE_FLYER" \
  --name     "$BUSINESS_NAME" \
  --url      "$PREVIEW_URL" \
  --template "$TEMPLATE" \
  --output   "$ASSETS_OUTPUT"

# =============================================================================
# COPY TO SITE (if directory exists)
# =============================================================================
if [ -d "$SITE_DIR" ]; then
  cp "$ASSETS_OUTPUT" "$SITE_OUTPUT"
  echo "📋  Also copied → $SITE_OUTPUT"
fi

# =============================================================================
# DONE
# =============================================================================
FLYER_SIZE=$(stat -c%s "$ASSETS_OUTPUT" 2>/dev/null || echo 0)
FLYER_STR=$(numfmt --to=iec "$FLYER_SIZE" 2>/dev/null || echo "${FLYER_SIZE}B")

echo ""
echo "═══════════════════════════════════════════════════"
echo "  📊  Result"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📐  File size : $FLYER_STR"
echo "  💰  Cost      : \$0.00  (local rendering)"
echo ""
echo "  🖨️   Open: xdg-open \"$ASSETS_OUTPUT\""
echo ""
