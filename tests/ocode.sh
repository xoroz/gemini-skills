#!/usr/bin/env bash
# test_opencode.sh — systematic pre-flight for opencode serve+run --attach HTML generation
# Tests all 5 open questions before any create.sh changes.
set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
PORT=4097                          # avoid collision with any existing serve on 4096
WORKDIR=/tmp/oc-test-$$            # isolated, no project context
MODEL="${OPENCODE_MODEL:-openrouter/google/gemini-2.5-flash-lite}"
SERVE_PID=""
LOG_DIR=/tmp/oc-test-logs-$$

# Minimal HTML prompt (~5K token equivalent target)
HTML_PROMPT='Output ONLY raw HTML. No markdown, no explanation, no code fences.
Generate a single self-contained HTML page with:
- A heading: "Test Page"
- A paragraph of lorem ipsum
- A small CSS block making the background #f0f0f0
Output must start with <!DOCTYPE html> and end with </html>.'

# ── helpers ───────────────────────────────────────────────────────────────────
pass() { echo "  [PASS] $*"; }
fail() { echo "  [FAIL] $*"; }
info() { echo ""; echo "==> $*"; }
cleanup() {
    [[ -n "$SERVE_PID" ]] && kill "$SERVE_PID" 2>/dev/null || true
    rm -rf "$WORKDIR" "$LOG_DIR"
}
trap cleanup EXIT

mkdir -p "$WORKDIR" "$LOG_DIR"

# ── start serve: cd into WORKDIR, no --dir flag ───────────────────────────────
info "Starting opencode serve (cwd=$WORKDIR) --port $PORT"
(
    cd "$WORKDIR"
    exec opencode serve --hostname 127.0.0.1 --port "$PORT"
) > "$LOG_DIR/serve.stdout" 2> "$LOG_DIR/serve.stderr" &
SERVE_PID=$!

for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:$PORT/global/health" > /dev/null 2>&1; then
        pass "serve is up (pid=$SERVE_PID)"
        break
    fi
    sleep 1
    if [[ $i -eq 20 ]]; then
        fail "serve did not come up after 20s"
        echo "--- serve stderr ---"
        cat "$LOG_DIR/serve.stderr"
        exit 1
    fi
done

ATTACH="http://127.0.0.1:$PORT"

# ── Q1: does run --attach without --dir give non-empty JSON for an HTML prompt? ──
info "Q1: run --attach (no --dir) → non-empty JSON for HTML prompt"
T1_START=$(date +%s%3N)

set +e
Q1_OUT=$(opencode run \
    --attach "$ATTACH" \
    --model "$MODEL" \
    --format json \
    -q \
    "$HTML_PROMPT" 2> "$LOG_DIR/q1.stderr")
Q1_RC=$?
set -e

T1_END=$(date +%s%3N)
T1_MS=$(( T1_END - T1_START ))

echo "  exit_code=$Q1_RC  bytes=${#Q1_OUT}  latency=${T1_MS}ms"

if [[ $Q1_RC -ne 0 ]]; then
    fail "run exited non-zero ($Q1_RC)"
    echo "  stderr:"
    cat "$LOG_DIR/q1.stderr"
else
    if [[ -z "$Q1_OUT" ]]; then
        fail "output is empty"
    else
        pass "got non-empty output"
        echo "$Q1_OUT" > "$LOG_DIR/q1.json"
    fi
fi

# ── Q2: is the HTML in a text event (not a file-write tool call)? ─────────────
info "Q2: HTML arrives as text content (not tool/write event)"
if [[ -s "$LOG_DIR/q1.json" ]]; then
    # Check for tool_use blocks (file write attempts)
    HAS_TOOL=$(echo "$Q1_OUT" | jq 'if type=="array" then .[].type else .type end' 2>/dev/null \
        | grep -c "tool_use" || true)
    HAS_TEXT=$(echo "$Q1_OUT" | jq -r '
        if type=="array" then .[].content // .[].text // ""
        else .content // .text // ""
        end' 2>/dev/null | grep -c "<!DOCTYPE\|<html" || true)

    if [[ "$HAS_TOOL" -gt 0 ]]; then
        fail "model attempted file write tool calls (tool_use blocks: $HAS_TOOL)"
    else
        pass "no tool_use blocks"
    fi

    if [[ "$HAS_TEXT" -gt 0 ]]; then
        pass "HTML found in text content"
    else
        fail "no HTML found in text content — check $LOG_DIR/q1.json"
        echo "  raw (first 500 chars):"
        echo "$Q1_OUT" | head -c 500
    fi
else
    fail "skipped — no q1.json to inspect"
fi

# ── Q3: ANSI codes in JSON output? ────────────────────────────────────────────
info "Q3: ANSI escape codes in --format json output"
if [[ -s "$LOG_DIR/q1.json" ]]; then
    ANSI_COUNT=$(cat "$LOG_DIR/q1.json" | grep -cP '\x1b\[' || true)
    if [[ "$ANSI_COUNT" -gt 0 ]]; then
        fail "ANSI codes found ($ANSI_COUNT occurrences) — need to strip"
    else
        pass "JSON is clean (no ANSI codes)"
    fi
else
    fail "skipped — no q1.json"
fi

# ── Q4: how much context does opencode inject with WORKDIR vs /tmp isolation? ──
info "Q4: token context check — workdir=$WORKDIR vs project dir"
# Ask the model to report what context it sees
set +e
Q4_OUT=$(opencode run \
    --attach "$ATTACH" \
    --model "$MODEL" \
    --format json \
    -q \
    "Reply with ONE line only: how many files or context items were injected into your context by the system? Format: FILES:<n> TOKENS:<estimate>" \
    2>/dev/null)
set -e

if [[ -n "$Q4_OUT" ]]; then
    pass "context probe returned output"
    echo "  raw: $(echo "$Q4_OUT" | head -c 300)"
else
    info "  (no output from context probe — check manually)"
fi

# Check if WORKDIR has any files injected automatically
FILE_COUNT=$(find "$WORKDIR" -type f | wc -l)
echo "  workdir file count: $FILE_COUNT  (should be 0 for isolation)"
if [[ $FILE_COUNT -eq 0 ]]; then
    pass "workdir is clean — minimal context injection expected"
else
    fail "workdir has $FILE_COUNT files — context may be polluted"
    find "$WORKDIR" -type f
fi

# ── Q5: latency for the HTML prompt ──────────────────────────────────────────
info "Q5: latency summary"
echo "  model:   $MODEL"
echo "  latency: ${T1_MS}ms  (${T1_MS} ms end-to-end including serve overhead)"
if [[ $T1_MS -lt 5000 ]]; then
    pass "fast (<5s)"
elif [[ $T1_MS -lt 15000 ]]; then
    pass "acceptable (5-15s)"
else
    fail "slow (>${T1_MS}ms) — may be a problem for automation"
fi

# ── summary ───────────────────────────────────────────────────────────────────
info "Artifacts saved to $LOG_DIR (persisted after script — cleanup manually)"
trap - EXIT   # keep logs, only kill serve
[[ -n "$SERVE_PID" ]] && kill "$SERVE_PID" 2>/dev/null || true
rm -rf "$WORKDIR"

echo ""
echo "Done. Check $LOG_DIR/q1.json for the raw JSON response."
echo "If Q1+Q2+Q3 all pass → safe to proceed with create.sh changes."
