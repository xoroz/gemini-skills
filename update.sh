#!/usr/bin/env bash
# ──────────────────────────────────────────────
# TexNGo Auto-Update Script
# Pulls latest changes from GitHub if available.
# Designed to run via crontab every 30 minutes:
#   */30 * * * * /home/felix/projects/gemini-skills/update.sh
# ──────────────────────────────────────────────

set -euo pipefail

# ── Ensure cron-safe PATH ──
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BRANCH="main"
LOG_FILE="$REPO_DIR/logs/update.log"
ENV_FILE="$REPO_DIR/.env"

cd "$REPO_DIR"
mkdir -p "$REPO_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# ── Load .env (handles spaces/quotes safely) ──
if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r key value; do
        # skip blank lines and comments
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
        # trim surrounding whitespace from key
        key="$(echo "$key" | xargs)"
        # strip optional surrounding quotes from value
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key=$value"
    done < "$ENV_FILE"
fi

# ── Auth: inject GITHUB_API_KEY into remote URL ──
if [ -n "${GITHUB_API_KEY:-}" ]; then
    REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$REMOTE_URL" == https://github.com/* ]] && [[ "$REMOTE_URL" != *"@"* ]]; then
        REPO_PATH="${REMOTE_URL#https://github.com/}"
        git remote set-url origin "https://${GITHUB_API_KEY}@github.com/${REPO_PATH}"
    fi
fi

# ── Fetch remote ──
log "Fetching origin/$BRANCH..."
if ! git fetch origin "$BRANCH" --quiet 2>&1; then
    log "ERROR: git fetch failed. Check network or credentials."
    exit 1
fi

# ── Check for changes ──
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    log "Already up to date ($LOCAL_HEAD)."
    exit 0
fi

# ── Changes detected → pull ──
log "Changes detected — pulling..."
log "  Local:  $LOCAL_HEAD"
log "  Remote: $REMOTE_HEAD"

# Stash any local changes so pull doesn't fail
STASHED=false
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    log "  Stashing local changes..."
    git stash push -m "auto-update-$(date +%s)" --quiet
    STASHED=true
fi

if ! git pull origin "$BRANCH" --ff-only --quiet 2>&1; then
    log "ERROR: git pull --ff-only failed. Manual intervention may be needed."
    # Restore stash if we stashed
    if [ "$STASHED" = true ]; then
        git stash pop --quiet 2>/dev/null || true
    fi
    exit 1
fi

# Restore stashed changes
if [ "$STASHED" = true ]; then
    if ! git stash pop --quiet 2>/dev/null; then
        log "WARNING: Could not restore stashed changes (conflict?). They remain in stash."
    fi
fi

NEW_HEAD=$(git rev-parse HEAD)
log "Updated to $NEW_HEAD"

# ── Reinstall dependencies if requirements.txt changed ──
if git diff --name-only "$LOCAL_HEAD" "$NEW_HEAD" | grep -q "^requirements.txt$"; then
    log "requirements.txt changed — reinstalling dependencies..."
    if "$REPO_DIR/venv/bin/pip" install -r "$REPO_DIR/requirements.txt" --quiet 2>&1; then
        log "Dependencies reinstalled successfully."
    else
        log "WARNING: pip install failed. Check requirements.txt or venv."
    fi
fi

# ── Reload service (requires NOPASSWD in sudoers or user-level systemd) ──
if systemctl --user restart auto-sites.service 2>/dev/null; then
    log "Restarted auto-sites.service (user unit)."
elif sudo -n systemctl restart auto-sites.service 2>/dev/null; then
    log "Restarted auto-sites.service (system unit via sudo -n)."
else
    log "WARNING: Could not restart auto-sites.service. Restart manually if needed."
fi

log "Done."
