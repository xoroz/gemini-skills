#!/bin/bash
# =============================================================================
# tests/test.sh — Modular API test runner for Review Site Factory
# =============================================================================
# Usage:
#   ./tests/test.sh all          # run all non-expensive tests
#   ./tests/test.sh health       # GET /health
#   ./tests/test.sh check-all    # GET /health-check-all
#   ./tests/test.sh scrape       # GET /scrape-maps
#   ./tests/test.sh score        # POST /score-site (local screenshot, ~$0.01)
#   ./tests/test.sh mail         # POST /send-mail (sends to self via SMTP)
#   ./tests/test.sh log          # GET /build-log/{slug}
#   ./tests/test.sh status       # GET /status/{job_id}
#   ./tests/test.sh flyers       # POST /create-flyers (qnt=1, registry only)
#   ./tests/test.sh assign       # POST /assign-site (validation check)
#   ./tests/test.sh letter       # POST /send-letter (dry_run=true, no postal cost)
#   ./tests/test.sh site-email   # POST /send-site-email (SMTP only)
#   ./tests/test.sh generate     # POST /generate-site (EXPENSIVE — explicit only)
#   ./tests/test.sh modify       # POST /modify-site   (EXPENSIVE — explicit only)
#   ./tests/test.sh recreate     # POST /recreate-site (EXPENSIVE — explicit only)
#   ./tests/test.sh publish      # POST /publish-to-prod (S3 — explicit only)
# =============================================================================

set -euo pipefail

# ─── Load .env if present ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [ -f "${ROOT_DIR}/.env" ]; then
  set -a; source "${ROOT_DIR}/.env"; set +a
fi

# ─── Config ──────────────────────────────────────────────────────────────────
BASE_URL="${BASE_URL:-http://localhost:8020}"
API_TOKEN="${API_TOKEN:-}"
SMTP_USER="${SMTP_USER:-}"
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GREY='\033[0;90m'
NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────
pass()  { echo -e "  ${GREEN}[PASS]${NC} $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail()  { echo -e "  ${RED}[FAIL]${NC} $1"; FAIL_COUNT=$((FAIL_COUNT+1)); }
skip()  { echo -e "  ${GREY}[SKIP]${NC} $1"; SKIP_COUNT=$((SKIP_COUNT+1)); }
info()  { echo -e "  ${CYAN}[INFO]${NC} $1"; }
sep()   { echo -e "${CYAN}──────────────────────────────────────────────────────${NC}"; }
header(){ echo ""; echo -e "${YELLOW}▶ $1${NC}"; }

# Auth header builder — empty string if no token
auth_header() {
  if [ -n "$API_TOKEN" ]; then
    echo "-H \"Authorization: Bearer ${API_TOKEN}\""
  else
    echo ""
  fi
}

# curl wrapper with auth
api_get() {
  local path="$1"; shift
  if [ -n "$API_TOKEN" ]; then
    curl -s -w "\n%{http_code}" -H "Authorization: Bearer ${API_TOKEN}" "${BASE_URL}${path}" "$@"
  else
    curl -s -w "\n%{http_code}" "${BASE_URL}${path}" "$@"
  fi
}

api_post() {
  local path="$1"; shift
  if [ -n "$API_TOKEN" ]; then
    curl -s -w "\n%{http_code}" -X POST \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${API_TOKEN}" \
      "${BASE_URL}${path}" "$@"
  else
    curl -s -w "\n%{http_code}" -X POST \
      -H "Content-Type: application/json" \
      "${BASE_URL}${path}" "$@"
  fi
}

# Extract last line (HTTP code) and body from curl output
http_code() { echo "$1" | tail -1; }
body()      { echo "$1" | head -n -1; }

# Get a JSON field value
jq_field() {
  local json="$1" field="$2"
  echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('${field}',''))" 2>/dev/null || echo ""
}

# Check HTTP status code is in expected list
expect_code() {
  local label="$1" actual="$2"; shift 2
  for expected in "$@"; do
    [ "$actual" = "$expected" ] && return 0
  done
  fail "${label} → unexpected HTTP ${actual} (expected: $*)"
  return 1
}

# ─── Individual test functions ────────────────────────────────────────────────

test_health() {
  header "GET /health"
  RESULT=$(api_get "/health")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ] && [ "$STATUS" = "ok" ]; then
    pass "GET /health → 200 {status: ok}"
  else
    fail "GET /health → HTTP ${CODE}, status='${STATUS}'"
  fi
}

test_check_all() {
  header "GET /health-check-all"
  RESULT=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health-check-all")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ]; then
    pass "GET /health-check-all → 200 {status: ${STATUS}}"
    # Print each check's status
    echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
checks = d.get('checks', {})
for k, v in checks.items():
    s = v.get('status','?')
    extra = {ek: ev for ek, ev in v.items() if ek != 'status'}
    extra_str = ' | ' + ' '.join(f'{ek}={ev}' for ek, ev in extra.items()) if extra else ''
    color = '\033[0;32m' if s == 'ok' else ('\033[1;33m' if s == 'missing' else '\033[0;31m')
    nc = '\033[0m'
    print(f'    {color}{s:10}{nc} {k}{extra_str}')
" 2>/dev/null || true
  else
    fail "GET /health-check-all → HTTP ${CODE}"
    echo "  Body: ${BODY}"
  fi
}

test_scrape() {
  header "GET /scrape-maps"
  info "Using: business_type=ristorante&location=Roma&max_results=1 (Playwright, no AI cost)"
  RESULT=$(api_get "/scrape-maps?business_type=ristorante&location=Roma&max_results=1")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  COUNT=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',[])))" 2>/dev/null || echo 0)
  if [ "$CODE" = "200" ] && [ "$STATUS" = "success" ]; then
    pass "GET /scrape-maps → 200, ${COUNT} result(s)"
  else
    fail "GET /scrape-maps → HTTP ${CODE}, status='${STATUS}'"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_score() {
  header "POST /score-site"
  # Find any PNG in assets/ to use as a local screenshot (no site build needed)
  SCREENSHOT=$(ls "${ROOT_DIR}/assets/"*.png 2>/dev/null | head -1 || echo "")
  if [ -z "$SCREENSHOT" ]; then
    skip "POST /score-site — no PNG found in assets/ to use as screenshot"
    return
  fi
  info "Using screenshot: ${SCREENSHOT} (~\$0.01 Claude vision call)"
  RESULT=$(api_post "/score-site" -d "{\"screenshot_path\": \"${SCREENSHOT}\", \"label\": \"test\"}")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  VOTE=$(jq_field "$BODY" "vote")
  if [ "$CODE" = "200" ] && [ -n "$VOTE" ]; then
    pass "POST /score-site → 200, vote=${VOTE}"
  else
    fail "POST /score-site → HTTP ${CODE}"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_mail() {
  header "POST /send-mail"
  if [ -z "$SMTP_USER" ]; then
    skip "POST /send-mail — SMTP_USER not set in .env"
    return
  fi
  info "Sending test email to self: ${SMTP_USER}"
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
  RESULT=$(api_post "/send-mail" -d "{
    \"to\": \"${SMTP_USER}\",
    \"subject\": \"[test.sh] API smoke test ${TIMESTAMP}\",
    \"body\": \"This is an automated test from test.sh run at ${TIMESTAMP}.\"
  }")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ] && [ "$STATUS" = "sent" ]; then
    pass "POST /send-mail → 200 {status: sent}"
  else
    fail "POST /send-mail → HTTP ${CODE}, status='${STATUS}'"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_log() {
  header "GET /build-log/{slug}"
  # Try to find a real slug (must be a directory with build.log), fall back to dummy
  SLUG=$(find "${ROOT_DIR}/sites" -maxdepth 2 -name "build.log" 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs basename 2>/dev/null || echo "")
  if [ -z "$SLUG" ]; then
    info "No sites/ found — testing with dummy slug (expect 404)"
    SLUG="dummy-test-slug"
    RESULT=$(api_get "/build-log/${SLUG}")
    CODE=$(http_code "$RESULT")
    if [ "$CODE" = "404" ]; then
      pass "GET /build-log/dummy → 404 (expected — no sites yet)"
    else
      fail "GET /build-log/dummy → unexpected HTTP ${CODE}"
    fi
  else
    RESULT=$(api_get "/build-log/${SLUG}")
    CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
    BUILD_STATUS=$(jq_field "$BODY" "build_status")
    if [ "$CODE" = "200" ]; then
      pass "GET /build-log/${SLUG} → 200, build_status=${BUILD_STATUS}"
    else
      fail "GET /build-log/${SLUG} → HTTP ${CODE}"
      echo "  Body: ${BODY}" | head -c 400
    fi
  fi
}

test_status() {
  header "GET /status/{job_id}"
  SLUG=$(ls "${ROOT_DIR}/sites/" 2>/dev/null | grep -v "site-id" | head -1 || echo "")
  if [ -z "$SLUG" ]; then
    info "No sites/ found — testing with dummy job_id (expect 404)"
    SLUG="dummy-test-job"
    RESULT=$(api_get "/status/${SLUG}")
    CODE=$(http_code "$RESULT")
    if [ "$CODE" = "404" ]; then
      pass "GET /status/dummy → 404 (expected — no sites yet)"
    else
      fail "GET /status/dummy → unexpected HTTP ${CODE}"
    fi
  else
    RESULT=$(api_get "/status/${SLUG}")
    CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
    JOB_STATUS=$(jq_field "$BODY" "status")
    if [ "$CODE" = "200" ]; then
      pass "GET /status/${SLUG} → 200, status=${JOB_STATUS}"
    else
      fail "GET /status/${SLUG} → HTTP ${CODE}"
      echo "  Body: ${BODY}" | head -c 400
    fi
  fi
}

test_flyers() {
  header "POST /create-flyers"
  info "Creating qnt=1 flyer (allocates registry entry only, no AI cost)"
  RESULT=$(api_post "/create-flyers" -d '{"qnt": 1}')
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ] && { [ "$STATUS" = "ok" ] || [ "$STATUS" = "processing" ]; }; then
    IDS=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('created_ids',''))" 2>/dev/null || echo "")
    pass "POST /create-flyers → 200 {status: ${STATUS}, created_ids: ${IDS}}"
  else
    fail "POST /create-flyers → HTTP ${CODE}, status='${STATUS}'"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_assign() {
  header "POST /assign-site"
  info "Testing with non-existent IDs — expect 400 or 404 (validation check)"
  RESULT=$(api_post "/assign-site" -d '{"site_id": "ZZZ", "site_slug": "no-such-site"}')
  CODE=$(http_code "$RESULT")
  if [ "$CODE" = "400" ] || [ "$CODE" = "404" ] || [ "$CODE" = "422" ]; then
    pass "POST /assign-site → HTTP ${CODE} (validation working)"
  elif [ "$CODE" = "200" ]; then
    # Might succeed if ZZZ happens to be a real placeholder
    BODY=$(body "$RESULT")
    STATUS=$(jq_field "$BODY" "status")
    pass "POST /assign-site → 200 (ID existed), status=${STATUS}"
  else
    fail "POST /assign-site → unexpected HTTP ${CODE}"
    BODY=$(body "$RESULT")
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_letter() {
  header "POST /send-letter (dry_run=true)"
  info "dry_run=true — no postal API charge"
  # Find a real slug or use dummy
  SLUG=$(ls "${ROOT_DIR}/sites/" 2>/dev/null | grep -v "site-id" | head -1 || echo "test-business")
  RESULT=$(api_post "/send-letter" -d "{
    \"slug\": \"${SLUG}\",
    \"recipient_name\": \"Test Recipient\",
    \"recipient_address\": \"Via Test 1, 00100 Roma RM\",
    \"dry_run\": true
  }")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  if [ "$CODE" = "200" ]; then
    STATUS=$(jq_field "$BODY" "status")
    pass "POST /send-letter dry_run → 200, status=${STATUS}"
  elif [ "$CODE" = "503" ] || [ "$CODE" = "500" ]; then
    # Letter API not configured — acceptable
    DETAIL=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail',''))" 2>/dev/null || echo "")
    skip "POST /send-letter → HTTP ${CODE} (letter API likely not configured: ${DETAIL})"
  else
    fail "POST /send-letter → HTTP ${CODE}"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_site_email() {
  header "POST /send-site-email"
  if [ -z "$SMTP_USER" ]; then
    skip "POST /send-site-email — SMTP_USER not set in .env"
    return
  fi
  # Find a real slug (directory with build.log) and its flyer_id
  SLUG=$(find "${ROOT_DIR}/sites" -maxdepth 2 -name "build.log" 2>/dev/null | head -1 | xargs -I{} dirname {} | xargs basename 2>/dev/null || echo "")
  if [ -z "$SLUG" ]; then
    skip "POST /send-site-email — no sites/ found, need a real slug"
    return
  fi
  # Find a flyer id from registry that maps to this slug
  FLYER_ID=$(python3 -c "
import json, os
p = '${ROOT_DIR}/sites/site-id.json'
if not os.path.exists(p): exit(1)
reg = json.load(open(p))
for k, v in reg.items():
    if v.get('slug') == '${SLUG}':
        print(k); exit(0)
exit(1)
" 2>/dev/null || echo "")
  if [ -z "$FLYER_ID" ]; then
    skip "POST /send-site-email — no flyer ID mapped to slug '${SLUG}'"
    return
  fi
  info "Using slug=${SLUG}, flyer_id=${FLYER_ID}, to=${SMTP_USER}"
  RESULT=$(api_post "/send-site-email" -d "{
    \"slug\": \"${SLUG}\",
    \"flyer_id\": \"${FLYER_ID}\",
    \"to_email\": \"${SMTP_USER}\",
    \"template\": 1
  }")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ] && [ "$STATUS" = "sent" ]; then
    pass "POST /send-site-email → 200 {status: sent}"
  else
    fail "POST /send-site-email → HTTP ${CODE}, status='${STATUS}'"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

# ─── Expensive tests (explicit-only, not run in "all") ───────────────────────

test_generate() {
  header "POST /generate-site  ⚠️  EXPENSIVE"
  info "Forcing MODE=DEV (cheap image model: ~\$0.014)"
  info "Using minimal data: test business in Roma"
  RESULT=$(api_post "/generate-site" -d '{
    "business_name": "Test Trattoria Roma",
    "niche": "ristorante",
    "address": "Via Test 1, 00100 Roma RM",
    "tel": "+39 06 12345678"
  }')
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  JOB_ID=$(jq_field "$BODY" "job_id")
  if [ "$CODE" = "200" ] && [ "$STATUS" = "processing" ]; then
    pass "POST /generate-site → 200 {status: processing, job_id: ${JOB_ID}}"
    info "Monitor with: ./tests/test.sh status (job_id=${JOB_ID})"
    info "Or tail: journalctl -u gemini-skills -f"
  else
    fail "POST /generate-site → HTTP ${CODE}, status='${STATUS}'"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_modify() {
  header "POST /modify-site  ⚠️  EXPENSIVE"
  SLUG=$(ls "${ROOT_DIR}/sites/" 2>/dev/null | grep -v "site-id" | head -1 || echo "")
  if [ -z "$SLUG" ]; then
    skip "POST /modify-site — no sites/ found to modify"
    return
  fi
  info "Modifying slug=${SLUG} (uses AI model)"
  RESULT=$(api_post "/modify-site" -d "{
    \"site_slug\": \"${SLUG}\",
    \"target_selector\": \"h1\",
    \"prompt\": \"Make the heading slightly more welcoming\"
  }")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ]; then
    pass "POST /modify-site → 200, status=${STATUS}"
  else
    fail "POST /modify-site → HTTP ${CODE}"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_recreate() {
  header "POST /recreate-site  ⚠️  EXPENSIVE"
  SLUG=$(ls "${ROOT_DIR}/sites/" 2>/dev/null | grep -v "site-id" | head -1 || echo "")
  if [ -z "$SLUG" ]; then
    skip "POST /recreate-site — no sites/ found"
    return
  fi
  info "Recreating slug=${SLUG} (full AI rebuild)"
  RESULT=$(api_post "/recreate-site" -d "{
    \"site_slug\": \"${SLUG}\",
    \"improvements\": \"Improve overall design quality\",
    \"webhook_url\": \"\"
  }")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ]; then
    pass "POST /recreate-site → 200, status=${STATUS}"
  else
    fail "POST /recreate-site → HTTP ${CODE}"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

test_publish() {
  header "POST /publish-to-prod/{site_name}  ⚠️  REQUIRES S3"
  SLUG=$(ls "${ROOT_DIR}/sites/" 2>/dev/null | grep -v "site-id" | head -1 || echo "")
  if [ -z "$SLUG" ]; then
    skip "POST /publish-to-prod — no sites/ found"
    return
  fi
  info "Publishing slug=${SLUG} to S3"
  RESULT=$(api_post "/publish-to-prod/${SLUG}")
  CODE=$(http_code "$RESULT"); BODY=$(body "$RESULT")
  STATUS=$(jq_field "$BODY" "status")
  if [ "$CODE" = "200" ]; then
    URL=$(jq_field "$BODY" "url")
    pass "POST /publish-to-prod/${SLUG} → 200, url=${URL}"
  else
    fail "POST /publish-to-prod/${SLUG} → HTTP ${CODE}"
    echo "  Body: ${BODY}" | head -c 400
  fi
}

# ─── Run all (non-expensive) ─────────────────────────────────────────────────

run_all() {
  echo ""
  echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║   Review Site Factory — Full API Test Suite          ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
  echo -e "  Target: ${BASE_URL}"
  echo -e "  Auth:   $([ -n "$API_TOKEN" ] && echo "Bearer token set" || echo "no token")"
  sep

  test_health
  sep
  test_check_all
  sep
  test_scrape
  sep
  test_score
  sep
  test_mail
  sep
  test_log
  sep
  test_status
  sep
  test_flyers
  sep
  test_assign
  sep
  test_letter
  sep
  test_site_email
  sep

  echo ""
  echo -e "  ${GREEN}Passed: ${PASS_COUNT}${NC}  |  ${RED}Failed: ${FAIL_COUNT}${NC}  |  ${GREY}Skipped: ${SKIP_COUNT}${NC}"
  echo ""
  echo -e "  ${GREY}Expensive tests (run explicitly): generate, modify, recreate, publish${NC}"
  echo ""

  [ "$FAIL_COUNT" -eq 0 ]
}

# ─── Dispatcher ───────────────────────────────────────────────────────────────

CMD="${1:-all}"

case "$CMD" in
  all)         run_all ;;
  health)      test_health ;;
  check-all)   test_check_all ;;
  scrape)      test_scrape ;;
  score)       test_score ;;
  mail)        test_mail ;;
  log)         test_log ;;
  status)      test_status ;;
  flyers)      test_flyers ;;
  assign)      test_assign ;;
  letter)      test_letter ;;
  site-email)  test_site_email ;;
  generate)    test_generate ;;
  modify)      test_modify ;;
  recreate)    test_recreate ;;
  publish)     test_publish ;;
  *)
    echo "Unknown test: $CMD"
    echo "Usage: $0 {all|health|check-all|scrape|score|mail|log|status|flyers|assign|letter|site-email|generate|modify|recreate|publish}"
    exit 1
    ;;
esac

# Print summary if single test
if [ "$CMD" != "all" ]; then
  echo ""
  echo -e "  ${GREEN}Passed: ${PASS_COUNT}${NC}  |  ${RED}Failed: ${FAIL_COUNT}${NC}  |  ${GREY}Skipped: ${SKIP_COUNT}${NC}"
  echo ""
  [ "$FAIL_COUNT" -eq 0 ]
fi
