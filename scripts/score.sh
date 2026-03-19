#!/bin/bash
# score.sh — Bash wrapper for score_site.py
#
# Usage:
#   ./scripts/score.sh sites/my-business/           # score a generated site dir
#   ./scripts/score.sh sites/my-business/index.html  # score by HTML path
#   ./scripts/score.sh scrapes/example.com/screenshot.png  # score existing screenshot
#   ./scripts/score.sh https://example.com           # screenshot + score a live URL
#
# Output: JSON printed to stdout; score.json written next to the site.

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  echo "Usage: $0 <site-dir | index.html | screenshot.png | https://url>"
  echo ""
  echo "Examples:"
  echo "  $0 sites/my-business/"
  echo "  $0 sites/my-business/index.html"
  echo "  $0 scrapes/example.com/screenshot.png"
  echo "  $0 https://example.com"
  exit 1
fi

if [[ "$TARGET" == http://* || "$TARGET" == https://* ]]; then
  uv run scripts/score_site.py --url "$TARGET" --label "url"

elif [[ "$TARGET" == *.png || "$TARGET" == *.jpg || "$TARGET" == *.jpeg || "$TARGET" == *.webp ]]; then
  LABEL="${2:-screenshot}"
  uv run scripts/score_site.py --screenshot "$TARGET" --label "$LABEL"

elif [[ "$TARGET" == *.html ]]; then
  SITE_DIR="$(dirname "$TARGET")"
  uv run scripts/score_site.py --html "$TARGET" --out "$SITE_DIR/score.json" --label "generated"
  echo ""
  echo "Score saved to: $SITE_DIR/score.json"

else
  # Treat as site directory
  INDEX="$TARGET/index.html"
  if [ -f "$INDEX" ]; then
    uv run scripts/score_site.py --html "$INDEX" --out "$TARGET/score.json" --label "generated"
    echo ""
    echo "Score saved to: $TARGET/score.json"
  else
    echo "❌ No index.html found in: $TARGET"
    exit 1
  fi
fi
