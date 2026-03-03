#!/bin/bash
# =============================================================================
# gen_mockup_assets.sh
#
# Generates the 6 generic placeholder images for .skel/assets/ using
# the nano-banana-pro image.py script (DEV model: flux.2-klein-4b).
#
# These images are used by MOCKUP mode in create.sh instead of dummy.png.
#
# Usage:
#   ./scripts/gen_mockup_assets.sh
#
# Env vars required (at least one):
#   OPENROUTER_API_KEY   — primary (used for flux.2-klein-4b)
#   GEMINI_API_KEY       — fallback
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_SCRIPT="$SCRIPT_DIR/skills/nano-banana-pro/scripts/image.py"
OUT_DIR="$SCRIPT_DIR/.skel/assets"

# DEV model — cheap & fast, no strict rate limits
MODEL="black-forest-labs/flux.2-klein-4b"

mkdir -p "$OUT_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  🎨  MOCKUP Asset Generator"
echo "═══════════════════════════════════════════════════"
echo "  Model  : $MODEL"
echo "  Output : $OUT_DIR"
echo "═══════════════════════════════════════════════════"
echo ""

# ---------------------------------------------------------------------------
# Image definitions: name -> prompt
# (Generic enough to work for ANY business niche)
# ---------------------------------------------------------------------------
declare -A IMAGES

IMAGES["hero"]="Professional hero photograph for a local business landing page. Beautiful storefront or service environment with warm, inviting light. Clean, modern commercial photography, wide cinematic composition."

IMAGES["gallery-1"]="Professional portfolio photograph showcasing a finished product or completed service. Clean studio-quality lighting, crisp detail, elegant presentation. Commercial photography for a business website."

IMAGES["gallery-2"]="Professional business portfolio photograph, different product or angle. Beautifully lit close-up of high-quality craftsmanship or a finished result. Premium commercial photography style."

IMAGES["workshop"]="Interior photograph of a clean, well-organised professional workspace or studio. Modern equipment, tidy shelves, warm ambient lighting. Commercial business photography."

IMAGES["detail"]="Extreme close-up macro photograph showing fine craftsmanship detail or a quality material texture. Shallow depth of field, crisp focus, elegant lighting. Product photography."

IMAGES["process"]="Action photograph of skilled hands at work performing a professional service. Warm documentary lighting, motion and energy, professional business photography."

# ---------------------------------------------------------------------------
TOTAL=${#IMAGES[@]}
COUNT=0
FAILED=0

for IMG_NAME in hero gallery-1 gallery-2 workshop detail process; do
  COUNT=$((COUNT + 1))
  OUT_PATH="$OUT_DIR/${IMG_NAME}.png"
  PROMPT="${IMAGES[$IMG_NAME]}"

  echo "  🖼️  [$COUNT/$TOTAL] Generating: ${IMG_NAME}.png"

  if uv run "$IMAGE_SCRIPT" \
      --prompt "$PROMPT" \
      --output "$OUT_PATH" \
      --aspect landscape \
      --quality draft \
      --model "$MODEL" 2>&1 | sed 's/^/     /'; then

    SIZE=$(stat -c%s "$OUT_PATH" 2>/dev/null || echo 0)
    if [ "$SIZE" -lt 5000 ]; then
      echo "     ❌ Image too small ($SIZE bytes) — likely invalid"
      FAILED=$((FAILED + 1))
    else
      SIZE_STR=$(numfmt --to=iec "$SIZE" 2>/dev/null || echo "${SIZE}B")
      echo "     ✅ Saved  (${SIZE_STR})"
    fi
  else
    echo "     ❌ image.py exited with error"
    FAILED=$((FAILED + 1))
  fi

  # Small courtesy delay between calls
  if [ $COUNT -lt $TOTAL ]; then
    sleep 2
  fi
done

echo ""
echo "═══════════════════════════════════════════════════"
echo "  📊  Done: $((TOTAL - FAILED))/$TOTAL generated  |  $FAILED failed"
echo "  📁  $OUT_DIR"
echo "═══════════════════════════════════════════════════"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo "⚠️  Some images failed. Re-run to retry."
  exit 1
fi
