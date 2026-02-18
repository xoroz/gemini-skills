#!/bin/bash
# =============================================================================
# tests/test-api.sh — API Smoke Tests for Review Site Factory
# =============================================================================
# Usage:
#   ./tests/test-api.sh                  # runs all tests against localhost:8000
#   BASE_URL=http://myserver:8000 ./tests/test-api.sh
# =============================================================================

BASE_URL="${BASE_URL:-http://localhost:8000}"
PASS=0
FAIL=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

separator() {
  echo -e "${CYAN}──────────────────────────────────────────────────────${NC}"
}

pass() { echo -e "  ${GREEN}✅ PASS${NC}: $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}❌ FAIL${NC}: $1"; FAIL=$((FAIL+1)); }

echo ""
echo -e "${CYAN}🧪 Review Site Factory — API Smoke Tests${NC}"
echo -e "   Target: ${BASE_URL}"
separator

# ─── Health check ─────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[1/3] Health check (GET /)${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "404" ]; then
  pass "Server is reachable (HTTP ${HTTP_CODE})"
else
  fail "Server not reachable at ${BASE_URL} (HTTP ${HTTP_CODE})"
  echo ""
  echo "  ⚠️  Make sure the API server is running:"
  echo "       source venv/bin/activate"
  echo "       uvicorn main:app --host 0.0.0.0 --port 8000"
  echo ""
  exit 1
fi

separator

# ─── Test 1: POST /generate-site ──────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/3] POST /generate-site${NC}"
echo "  Payload: Luigi Hair Salon (parrucchiere, La Spezia)"
echo ""

RESPONSE=$(curl -s -X POST "${BASE_URL}/generate-site" \
  -H "Content-Type: application/json" \
  -d '{
        "business_name": "Luigi Hair Salon",
        "niche": "parrucchiere",
        "address": "Via Roma 123, La Spezia, Italy",
        "tel": "+39 0187 123456",
        "webhook_url": "https://webhook.site/dummy-url-for-testing"
      }')

echo "  Response:"
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null | sed 's/^/  /'

STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
if [ "$STATUS" = "processing" ]; then
  pass "/generate-site returned status=processing"
else
  fail "/generate-site did not return status=processing (got: '$STATUS')"
fi

separator

# ─── Test 2: GET /scrape-maps ─────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/3] GET /scrape-maps${NC}"
echo "  Query: parrucchiere la spezia (max_results=3)"
echo "  ⏳ This may take 15-30 seconds (Playwright + Google Maps)..."
echo ""

RESPONSE=$(curl -s -X GET \
  "${BASE_URL}/scrape-maps?query=parrucchiere+la+spezia&max_results=3")

echo "  Response:"
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null | sed 's/^/  /'

SCRAPE_STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
if [ "$SCRAPE_STATUS" = "success" ]; then
  COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',[])))" 2>/dev/null)
  pass "/scrape-maps returned status=success with ${COUNT} result(s)"
else
  fail "/scrape-maps did not return status=success (got: '$SCRAPE_STATUS')"
fi

separator

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${GREEN}Passed: ${PASS}${NC}  |  ${RED}Failed: ${FAIL}${NC}"
echo ""
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
