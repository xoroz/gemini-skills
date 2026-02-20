#!/bin/bash
# =============================================================================
# scrape.sh — Query Google Maps via the Review Site Factory API
#
# Usage:
#   ./scrape.sh "Business Type" "Location" [max_results]
#
# Examples:
#   ./scrape.sh "parrucchiere" "la spezia"
#   ./scrape.sh "ristorante" "roma" 3
#   ./scrape.sh "mexican restaurant" "la spezia"
#   SITE_LANG=en ./scrape.sh "hair salon" "london"
#
# The query is combined as: "<business_type> <location>"
# and URL-encoded automatically by the API (spaces → +, etc.)
#
# Maps URL built by the server:
#   https://www.google.com/maps/search/<business_type>+<location>?hl=<SITE_LANG>
#
# Environment (can also be set in .env):
#   BASE_URL   — FastAPI server (default: http://localhost:8000)
#   SITE_LANG  — language for Maps results (default: it)
#   PORT       — API port; only used when BASE_URL is not set
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if present (system env vars always win)
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    if [ -z "${!key+x}" ]; then
      export "$line" 2>/dev/null || true
    fi
  done < "$SCRIPT_DIR/.env"
fi

# ── Args ─────────────────────────────────────────────────────────────────────
if [ $# -lt 2 ]; then
  echo "Usage: $0 \"Business Type\" \"Location\" [max_results]"
  echo ""
  echo "Examples:"
  echo "  $0 \"parrucchiere\" \"la spezia\""
  echo "  $0 \"ristorante\" \"roma\" 3"
  echo "  SITE_LANG=en $0 \"hair salon\" \"london\""
  exit 1
fi

BUSINESS_TYPE="$1"
LOCATION="$2"
MAX_RESULTS="${3:-1}"

# ── Config ───────────────────────────────────────────────────────────────────
PORT="${PORT:-8000}"
if [ -n "${BASE_URL:-}" ]; then
  API_BASE="${BASE_URL%/}"
else
  API_BASE="http://localhost:${PORT}"
fi
SITE_LANG="${SITE_LANG:-it}"

# ── URL encoding helper (pure bash, no python required) ───────────────────────
urlencode() {
  local string="$1"
  local encoded=""
  local i char
  for ((i = 0; i < ${#string}; i++)); do
    char="${string:$i:1}"
    case "$char" in
      [a-zA-Z0-9._~-]) encoded+="$char" ;;
      " ")              encoded+="+" ;;
      *)                printf -v hex '%%%02X' "'$char"; encoded+="$hex" ;;
    esac
  done
  echo "$encoded"
}

# Build the URL for display (same logic as the server)
COMBINED="${BUSINESS_TYPE} ${LOCATION}"
ENCODED="$(urlencode "$COMBINED")"
MAPS_URL="https://www.google.com/maps/search/${ENCODED}?hl=${SITE_LANG}"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "🔍 Review Site Factory — Google Maps Scraper"
echo "   API          : ${API_BASE}"
echo "   Business type: ${BUSINESS_TYPE}"
echo "   Location     : ${LOCATION}"
echo "   Max results  : ${MAX_RESULTS}"
echo "   Language     : ${SITE_LANG}"
echo "   Maps URL     : ${MAPS_URL}"
echo ""
echo "⏳ Scraping... (may take up to 30s)"
echo ""

# ── API call ─────────────────────────────────────────────────────────────────
BT_ENC="$(urlencode "$BUSINESS_TYPE")"
LOC_ENC="$(urlencode "$LOCATION")"

RESPONSE="$(curl -sf \
  "${API_BASE}/scrape-maps?business_type=${BT_ENC}&location=${LOC_ENC}&max_results=${MAX_RESULTS}" \
  --max-time 140 \
  -H "Accept: application/json")"

STATUS=$?
if [ $STATUS -ne 0 ]; then
  echo "❌ curl failed (exit $STATUS) — is the API server running at ${API_BASE}?"
  echo "   Start it with:  uvicorn main:app --host 0.0.0.0 --port ${PORT}"
  exit 1
fi

# ── Pretty output ─────────────────────────────────────────────────────────────
echo "📦 Response:"
echo ""

# Check for python3 for pretty-print; fall back to raw
if command -v python3 &>/dev/null; then
  echo "$RESPONSE" | python3 -m json.tool --indent 2
else
  echo "$RESPONSE"
fi

echo ""

# Quick summary if jq or python3 is available
if command -v python3 &>/dev/null; then
  STATUS_VAL="$(echo "$RESPONSE" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo '?')"
  COUNT="$(echo "$RESPONSE" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',[])))" 2>/dev/null || echo '?')"

  if [ "$STATUS_VAL" = "success" ]; then
    echo "✅ Status: success — ${COUNT} result(s) returned"
    if [ "${COUNT}" -gt 0 ] 2>/dev/null; then
      FIRST_NAME="$(echo "$RESPONSE" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(d['data'][0].get('business_name','?'))" 2>/dev/null || echo '?')"
      echo "   First result: ${FIRST_NAME}"
    fi
  else
    echo "⚠️  Status: ${STATUS_VAL}"
  fi
fi
echo ""
