#!/bin/bash

# Usage: ./create.sh [--website <url>] "Business Name" "Niche" "Address" "Contact Info"
#        --website <url>  Scrape the URL and use real data (frontend-clone mode)
# Language: Set SITE_LANG=en before running to generate in English (default: it)
# Mode:     Set MODE=DEV|PROD|SUPER|MOCKUP before running (default: DEV)
#
#   DEV   — cheap & fast    img: flux.2-klein-4b ($0.014)  text: gemini-2.5-flash
#   PROD  — balanced        img: gemini-2.5-flash-image ($0.038, 1K)  text: gemini-3-flash-preview
#   SUPER — highest quality img: gemini-3.1-flash-image-preview ($0.068, 0.5K)  text: gemini-3.1-pro-preview
#            NOTE: only gemini-3.1-flash-image-preview supports 0.5K resolution
#   MOCKUP — skip images (local dummy.png), text: gemini-2.5-flash-lite
#
# Examples:
#   ./create.sh "Officina Mario" "riparazione auto" "Via Roma 42, Milano" "+39 02 1234567"
#   SITE_LANG=en ./create.sh "Joe's Garage" "auto repair" "123 Main St" "555-1234"
#   MODE=DEV ./create.sh "Test Salon" "parrucchiere" "Via Test 1" "+39 000"
#   MODE=PROD ./create.sh "Ristorante Bella" "ristorante" "Via Po 1, Roma" "+39 06 9999"
#   MODE=SUPER ./create.sh "Hotel Lusso" "luxury hotel" "Piazza Navona 1" "+39 06 1111"
#   ./create.sh --website https://example.com "Agenzia Viaggi" "turismo" "Via Roma 1" "+39 0585 123"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- PARSE OPTIONAL FLAGS (before positional args) ---
# Supports both:  --website <url>   (CLI)
#                 WEBSITE_URL=<url> (env, used by FastAPI)
WEBSITE_URL="${WEBSITE_URL:-}"

_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --website)
      WEBSITE_URL="$2"
      shift 2
      ;;
    *)
      _args+=("$1")
      shift
      ;;
  esac
done
set -- "${_args[@]}"

# --- 0. ENV & PATH SETUP ---
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"

# Auto-detect node/npm from NVM if available
if [ -d "$HOME/.nvm" ]; then
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
fi

# Ensure gemini-cli is in path
if ! command -v gemini &> /dev/null; then
    # Last ditch attempt: check common nvm bin path pattern
    NVM_BIN=$(ls -d $HOME/.nvm/versions/node/*/bin 2>/dev/null | tail -n1 || echo "")
    if [ -n "$NVM_BIN" ]; then export PATH="$NVM_BIN:$PATH"; fi
fi

IMAGE_SCRIPT="$SCRIPT_DIR/skills/nano-banana-pro/scripts/image.py"
MAIL_SCRIPT="$SCRIPT_DIR/assets/bin/send_mail.py"
ID_MANAGER="$SCRIPT_DIR/scripts/id_manager.py"

# =============================================================================
# NOTIFICATION HELPER (needs to be defined before trap)
# =============================================================================
send_build_summary() {
  local status="$1"
  local emoji="✅"
  if [[ "$status" == "FAILED" ]]; then emoji="❌"; fi

  if [ -f "$MAIL_SCRIPT" ]; then
    echo "📩 Sending build summary email..."
    
    local subject="$emoji Build $status: $BUSINESS_NAME"
    local from="info@texngo.it"
    local to="info@texngo.it"
    
    # Check stats info availability
    local assets_sz_str="N/A"
    if [ -d "$FOLDER_NAME/assets" ]; then
        local sz=$(du -sb "$FOLDER_NAME/assets" 2>/dev/null | cut -f1 || echo 0)
        assets_sz_str=$(numfmt --to=iec $sz 2>/dev/null || echo "${sz}B")
    fi

    local log_content=""
    if [ -f "${LOG_FILE:-}" ] && [ -s "${LOG_FILE:-}" ]; then
        log_content=$(cat "$LOG_FILE")
    fi

    # Zip the site directory
    local zip_file=""
    if [ -n "$FOLDER_NAME" ] && [ -d "$FOLDER_NAME" ]; then
        zip_file="${FOLDER_NAME}.zip"
        local parent_dir=$(dirname "$FOLDER_NAME")
        local base_dir=$(basename "$FOLDER_NAME")
        (cd "$parent_dir" && zip -qr "${base_dir}.zip" "$base_dir")
    fi

    # Format body
    local body="
    🚀 Build Summary ($status): ${BUSINESS_NAME:-"Unknown"}
    ═══════════════════════════════════════════════
    🏢 Business : ${BUSINESS_NAME:-"Unknown"}
    🏷️ Niche    : ${NICHE:-"Unknown"}
    📍 Address  : ${ADDRESS:-"Unknown"}
    📞 Contact  : ${CONTACT:-"Unknown"}
    🏗️ Mode     : ${MODE:-"DEV"}
    🌐 Site URL : ${SITE_PUBLIC_URL:-"N/A"}
    
    📊 Stats
    ─────────────
    ⏱️ Time     : ${MINUTES:-"0"}m ${SECONDS:-"0"}s
    🖼️ Images   : ${IMAGES_GENERATED:-0} / ${IMG_TOTAL:-6}
    💰 Cost     : \$${TOTAL_COST:-"N/A"}
    📁 Assets   : $assets_sz_str
    
    ═══════════════════════════════════════════════
    Build log:
    ${log_content}
    "

    # Send via python utility
    local mail_args=("$from" "$to" "$subject" "$body")
    if [ -n "$zip_file" ] && [ -f "$zip_file" ]; then mail_args+=("$zip_file"); fi

    uv run "$MAIL_SCRIPT" "${mail_args[@]}" | sed 's/^/   /'
    echo "✅ Email notification sent!"
  fi
}

on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "❌ Script failed with exit code $exit_code."
        # Move failed build to _failed/ for inspection
        if [ -n "${FOLDER_NAME:-}" ] && [ -d "${FOLDER_NAME:-}" ]; then
            mkdir -p "sites/_failed"
            local failed_dest="sites/_failed/$(basename "$FOLDER_NAME")"
            rm -rf "$failed_dest"
            mv "$FOLDER_NAME" "$failed_dest"
            echo "📁 Moved failed build → $failed_dest"
        fi
        # Avoid trap loops
        trap - EXIT
        send_build_summary "FAILED"
    fi
}
# Trap will be enabled after input validation
# =============================================================================


# Load .env if present (system env vars always win)
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and blank lines
    [[ "$line" =~ ^\s*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # Only export if the var is not already set in the environment
    key="${line%%=*}"
    if [ -z "${!key+x}" ]; then
      export "$line" 2>/dev/null || true
    fi
  done < "$SCRIPT_DIR/.env"
fi

# REMOTE_SITE_URL — public web server root (optional)
# e.g. http://192.168.0.114  → sites at http://192.168.0.114/<slug>/index.html
REMOTE_SITE_URL="${REMOTE_SITE_URL%/}"  # strip trailing slash if any

# =============================================================================
# IMAGE MODEL & PRICING
# Override via .env:  AI_MODEL_IMG, AI_MODEL_TEXT, AI_COST_IMG
# =============================================================================
MODE="${MODE:-DEV}"  # DEV = cheap/fast, PROD = balanced quality, SUPER = max quality, MOCKUP = skip billing

if [ "$MODE" = "DEV" ]; then
  IMG_MODEL="${AI_MODEL_IMG:-black-forest-labs/flux.2-klein-4b}"
  IMG_COST_EACH="${AI_COST_IMG:-0.014}"
elif [ "$MODE" = "PROD" ]; then
  IMG_MODEL="${AI_MODEL_IMG:-google/gemini-2.5-flash-image}"
  IMG_COST_EACH="${AI_COST_IMG:-0.038}"
elif [ "$MODE" = "SUPER" ]; then
  # NOTE: 0.5K resolution is ONLY supported by gemini-3.1-flash-image-preview
  IMG_MODEL="${AI_MODEL_IMG:-google/gemini-3.1-flash-image-preview}"
  IMG_COST_EACH="${AI_COST_IMG:-0.068}"
else
  IMG_MODEL="mockup (local .skel)"
  IMG_COST_EACH=0
fi

# =============================================================================
# TEXT ENGINE: claude (default) or gemini
# Override via env: TEXT_ENGINE=gemini ./create.sh ...
# =============================================================================
TEXT_ENGINE="${TEXT_ENGINE:-claude}"  # claude or gemini

if [ "$TEXT_ENGINE" = "claude" ]; then
  TEXT_MODEL="${AI_MODEL_TEXT:-sonnet}"
else
  # Gemini models
  if [ "$MODE" = "MOCKUP" ]; then
    TEXT_MODEL="${AI_MODEL_TEXT:-gemini-2.5-flash-lite}"
  elif [ "$MODE" = "DEV" ]; then
    TEXT_MODEL="${AI_MODEL_TEXT:-gemini-2.5-flash}"
  elif [ "$MODE" = "PROD" ]; then
    TEXT_MODEL="${AI_MODEL_TEXT:-gemini-3-flash-preview}"
  else
    # SUPER
    TEXT_MODEL="${AI_MODEL_TEXT:-gemini-3.1-pro-preview}"
  fi
fi
# =============================================================================

# 1. READ INPUTS
BUSINESS_NAME="$1"
NICHE="$2"
ADDRESS="$3"
CONTACT="$4"
SITE_LANG="${SITE_LANG:-it}"  # Default: Italian

# Validate inputs
if [ -z "$BUSINESS_NAME" ] || [ -z "$NICHE" ]; then
  echo "❌ Error: Missing arguments."
  echo "Usage: ./create.sh \"Business Name\" \"Niche\" \"Address\" \"Contact Info\""
  echo "       SITE_LANG=en ./create.sh \"Business Name\" \"Niche\" \"Address\" \"Contact Info\""
  exit 1
fi

# Check API keys (need at least one)
if [ -z "$GEMINI_API_KEY" ] && [ -z "$OPENROUTER_API_KEY" ]; then
  echo "❌ Error: Set GEMINI_API_KEY or OPENROUTER_API_KEY environment variable."
  exit 1
fi

# 2. LANGUAGE CONFIGURATION
case "$SITE_LANG" in
  it)
    LANG_NAME="Italian"
    LANG_INSTRUCTION="ALL text content on the page MUST be written in Italian (Italiano). This includes headlines, descriptions, navigation labels, button text, form labels, testimonials, and footer text. Write natural, professional Italian — not machine-translated."
    SECTION_NAMES="1. Header/Nav (Navigazione fissa)
2. Hero (Titolo avvincente per $BUSINESS_NAME)
3. Servizi/Esperienze
4. Lavori Recenti/Galleria
5. Chi Siamo/La Nostra Storia
6. Il Nostro Processo
7. Testimonianze
8. Contatti con Modulo (Indirizzo: $ADDRESS e contatto: $CONTACT)
9. Footer"
    ;;
  en)
    LANG_NAME="English"
    LANG_INSTRUCTION="ALL text content on the page MUST be written in English."
    SECTION_NAMES="1. Header/Nav (Sticky)
2. Hero (Compelling headline for $BUSINESS_NAME)
3. Services/Experiences
4. Recent Work/Gallery
5. About/History
6. Our Process
7. Testimonials
8. Contact Info with Form (Include address: $ADDRESS and contact: $CONTACT)
9. Footer"
    ;;
  *)
    echo "⚠️  Unknown language '$SITE_LANG', defaulting to Italian (it)."
    SITE_LANG="it"
    LANG_NAME="Italian"
    LANG_INSTRUCTION="ALL text content on the page MUST be written in Italian (Italiano). This includes headlines, descriptions, navigation labels, button text, form labels, testimonials, and footer text. Write natural, professional Italian — not machine-translated."
    SECTION_NAMES="1. Header/Nav (Navigazione fissa)
2. Hero (Titolo avvincente per $BUSINESS_NAME)
3. Servizi/Esperienze
4. Lavori Recenti/Galleria
5. Chi Siamo/La Nostra Storia
6. Il Nostro Processo
7. Testimonianze
8. Contatti con Modulo (Indirizzo: $ADDRESS e contatto: $CONTACT)
9. Footer"
    ;;
esac

# 3. CREATE FOLDER STRUCTURE (inside sites/)
# Now that we have validated inputs, enable the error reporting trap
trap on_error EXIT

SITE_SLUG=$(echo "$BUSINESS_NAME" | sed -e 's/ /-/g' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-' | sed -E 's/--+/-/g' | sed -E 's/^-|-$//g')
FOLDER_NAME="sites/$SITE_SLUG"

if [ -d "$FOLDER_NAME" ]; then
  echo "⚠️  Folder $FOLDER_NAME already exists. Renaming to ${FOLDER_NAME}_old..."
  rm -rf "${FOLDER_NAME}_old"
  mv "$FOLDER_NAME" "${FOLDER_NAME}_old"
fi

LOG_FILE="$FOLDER_NAME/build.log"
BACKEND_LOG="$SCRIPT_DIR/logs/backend.log"

mkdir -p "$FOLDER_NAME/assets"

# Start logging — output goes to:
#   1. stdout (for main.py to capture via PIPE)
#   2. $LOG_FILE (per-site build.log)
#   3. $BACKEND_LOG (global log — tail -f logs/backend.log to watch everything)
exec > >(tee -a "$LOG_FILE" -a "$BACKEND_LOG") 2>&1

echo "═══════════════════════════════════════════════════"
echo "  🏗️  Landing Page Builder"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📂 Business: $BUSINESS_NAME"
echo "  🏷️  Niche:    $NICHE"
echo "  📍 Address:  $ADDRESS"
echo "  📞 Contact:  $CONTACT"
echo "  🌐 Language: $LANG_NAME ($SITE_LANG)"
echo "  🤖 Text:     $TEXT_ENGINE ($TEXT_MODEL)"
echo "  📁 Output:   $FOLDER_NAME/"
if [ -n "$WEBSITE_URL" ]; then
echo "  🔍 Clone:    $WEBSITE_URL"
fi
echo ""
echo "  ⏱️  Started:  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════"
echo ""

# 4. TRACK STATS
START_TIME=$(date +%s)
IMAGES_GENERATED=0
IMAGES_FAILED=0
IMAGES_VIA_GEMINI=0
IMAGES_VIA_OPENROUTER=0
# IMG_COST_EACH is set above in the MODEL & PRICING block

# 5. GENERATE LOCAL IMAGES WITH NANO-BANANA-PRO
echo "🎨 Generating images with Nano Banana Pro..."
echo "   Mode: $MODE  |  Model: $IMG_MODEL  |  ~\$${IMG_COST_EACH}/img"
echo ""

declare -A IMAGES
IMAGES["hero"]="Cinematic wide-angle shot of $BUSINESS_NAME ($NICHE). Focal point on the primary service/product with dramatic rim lighting. 8k resolution, shot on 35mm lens, high contrast, elegant commercial aesthetic, depth of field."
IMAGES["gallery-1"]="Pristine studio photograph of a $NICHE project. Neutral minimalist background, softbox lighting to eliminate harsh shadows, sharp focus, industrial design aesthetic, clean lines."
IMAGES["gallery-2"]="Alternative low-angle perspective of $NICHE equipment/product. Bold composition, accent lighting highlighting textures, high-end commercial catalog style, crisp details."
IMAGES["workshop"]="Wide interior shot of a $NICHE facility. Organized workspace, overhead industrial lighting mixed with natural window light, lived-in but clean professional atmosphere, bokeh background."
IMAGES["detail"]="Macro photography of $NICHE craftsmanship. Focus on material texture (metal, wood, or tech), shallow depth of field (f/2.8), warm golden hour lighting, hyper-realistic, intricate details."
IMAGES["process"]="Action candid of $NICHE workflow. Motion blur on hands, tactile engagement with tools, authentic workshop environment, documentary style, 4000k color temperature, professional grit."

IMG_COUNT=0
IMG_TOTAL=${#IMAGES[@]}

for IMG_NAME in "${!IMAGES[@]}"; do
  IMG_COUNT=$((IMG_COUNT + 1))
  IMG_PATH="$FOLDER_NAME/assets/${IMG_NAME}.png"
  IMG_PROMPT="${IMAGES[$IMG_NAME]}"
  
  echo "  🖼️  [$IMG_COUNT/$IMG_TOTAL] Generating: assets/${IMG_NAME}.png"
  
  if [ "$MODE" = "MOCKUP" ]; then
    cp "$SCRIPT_DIR/.skel/assets/dummy.png" "$IMG_PATH" || touch "$IMG_PATH"
    echo "     ✅ Copied dummy mockup image"
    IMAGES_GENERATED=$((IMAGES_GENERATED + 1))
    continue
  fi

  # Retry loop with exponential backoff for rate limits
  MAX_RETRIES=2
  RETRY=0
  SUCCESS=false

  # Image resolution: SUPER can use 0.5K (ONLY gemini-3.1-flash-image-preview supports it).
  # PROD uses 1K (gemini-2.5-flash-image does NOT support 0.5K). DEV also stays at 1K.
  if [ "$MODE" = "SUPER" ]; then
    IMG_SIZE_PARAM="${AI_IMG_SIZE:-0.5K}"
  else
    IMG_SIZE_PARAM="1K"
  fi

  while [ $RETRY -le $MAX_RETRIES ]; do
    OUTPUT=$(uv run "$IMAGE_SCRIPT" \
      --prompt "$IMG_PROMPT" \
      --output "$IMG_PATH" \
      --aspect landscape \
      --quality draft \
      --size "$IMG_SIZE_PARAM" \
      --model "$IMG_MODEL" 2>&1)
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
      IMG_SIZE=$(stat -c%s "$IMG_PATH" 2>/dev/null || stat -f%z "$IMG_PATH" 2>/dev/null || echo 0)
      if [ "$IMG_SIZE" -lt 5000 ]; then
        echo "     ❌ Error: Image ${IMG_NAME}.png is invalid (size too small: $IMG_SIZE bytes)."
        break
      fi

      echo "$OUTPUT" | sed 's/^/     /'
      SUCCESS=true
      IMAGES_GENERATED=$((IMAGES_GENERATED + 1))
      if echo "$OUTPUT" | grep -q "\[openrouter\]"; then
        IMAGES_VIA_OPENROUTER=$((IMAGES_VIA_OPENROUTER + 1))
      else
        IMAGES_VIA_GEMINI=$((IMAGES_VIA_GEMINI + 1))
      fi
      break
    fi

    # ── Failed — always log the full error for debugging ──
    RETRY=$((RETRY + 1))
    echo "     ❌ Attempt $RETRY failed (exit code $EXIT_CODE)."
    echo "     📋 Model: $IMG_MODEL  |  Size: $IMG_SIZE_PARAM"
    echo "     📋 Prompt: ${IMG_PROMPT:0:120}..."
    echo "$OUTPUT" | sed 's/^/     📋 /'
    echo "[IMG FAIL] ${IMG_NAME} attempt=$RETRY model=$IMG_MODEL exit=$EXIT_CODE" >> "$LOG_FILE"
    echo "$OUTPUT" >> "$LOG_FILE"

    # ── Classify the error ──
    if echo "$OUTPUT" | grep -qi "daily.limit\|403.*limit\|PerDay\|daily_limit"; then
      # DAILY LIMIT — no point retrying this or any remaining images
      echo "     🛑 DAILY QUOTA EXHAUSTED — aborting all remaining images."
      echo "        OpenRouter: check limit at https://openrouter.ai/settings/keys"
      echo "        Gemini: free tier daily cap hit, resets at midnight PT."
      IMAGES_FAILED=$((IMAGES_FAILED + 1))
      # Mark all remaining images as failed too
      REMAINING=$((IMG_TOTAL - IMG_COUNT))
      IMAGES_FAILED=$((IMAGES_FAILED + REMAINING))
      break 2  # break out of BOTH the retry loop and the image loop
    elif echo "$OUTPUT" | grep -qi "429\|RESOURCE_EXHAUSTED\|rate"; then
      # PER-MINUTE rate limit — worth retrying after backoff
      if [ $RETRY -le $MAX_RETRIES ]; then
        WAIT=$((30 * RETRY))  # 30s, 60s backoff
        echo "     ⏳ Rate limited (per-minute). Waiting ${WAIT}s before retry $RETRY/$MAX_RETRIES..."
        sleep $WAIT
      else
        echo "     ❌ Failed after $MAX_RETRIES retries (rate limited)."
      fi
    else
      # Non-rate-limit error — don't retry (bad prompt, auth error, etc.)
      echo "  ⚠️  Warning: Non-retryable error for ${IMG_NAME}.png, skipping."
      break
    fi
  done
  
  if [ "$SUCCESS" = false ]; then
    IMAGES_FAILED=$((IMAGES_FAILED + 1))
    echo "  ⚠️  Warning: Could not generate ${IMG_NAME}.png, continuing..."
  fi

  # Delay between requests (skip in DEV mode — cheap model has no rate limit concerns)
  if [ $IMG_COUNT -lt $IMG_TOTAL ] && [ "$MODE" != "DEV" ]; then
    echo "     ⏱️  Waiting 10s before next image (rate limit protection)..."
    sleep 10
  fi
done

echo ""
echo "✅ Images done! ($IMAGES_GENERATED/$IMG_TOTAL generated, $IMAGES_FAILED failed)"
echo ""

if [ "$IMAGES_FAILED" -gt 0 ]; then
  echo "❌ Error: $IMAGES_FAILED image(s) failed to generate correctly (or sizes were invalid). Aborting build."
  exit 1
fi

# 5b. OPTIMIZE IMAGES FOR WEB (PNG → WebP)
OPTIMIZE_SCRIPT="$SCRIPT_DIR/scripts/optimize_images.py"
if [ -f "$OPTIMIZE_SCRIPT" ] && [ "$MODE" != "MOCKUP" ]; then
  echo "🗜️  Optimizing images for web (PNG → WebP)..."
  uv run "$OPTIMIZE_SCRIPT" \
    --input "$FOLDER_NAME/assets/" \
    --quality 82 \
    --max-width 1200 \
    --max-height 900 \
    --replace 2>&1 | sed 's/^/   /'
  echo ""
fi


# 6a. SCRAPE SOURCE WEBSITE (if --website / WEBSITE_URL provided)
SCRAPED_DATA=""
SCRAPE_SKILL_SECTION=""
if [ -n "$WEBSITE_URL" ]; then
  SCRAPE_SCRIPT="$SCRIPT_DIR/scripts/scrape_site.py"
  PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
  if [ ! -f "$PYTHON_BIN" ]; then PYTHON_BIN="python3"; fi

  if [ -f "$SCRAPE_SCRIPT" ]; then
    echo "🔍 Scraping source website: $WEBSITE_URL"
    SCRAPE_OUT=$("$PYTHON_BIN" "$SCRAPE_SCRIPT" "$WEBSITE_URL" 2>&1)
    SCRAPE_EXIT=$?
    echo "$SCRAPE_OUT" | sed 's/^/   /'

    # Locate the raw.md file that was written
    SCRAPE_DOMAIN=$(python3 -c "
import re, sys
from urllib.parse import urlparse
u = sys.argv[1]
if not u.startswith('http'): u = 'https://' + u
domain = urlparse(u).netloc or u
print(re.sub(r'[^a-z0-9.-]', '-', domain.lower()).strip('-'))
" "$WEBSITE_URL" 2>/dev/null)
    SCRAPE_MD="$SCRIPT_DIR/scrapes/${SCRAPE_DOMAIN}/raw.md"

    if [ $SCRAPE_EXIT -eq 0 ] && [ -f "$SCRAPE_MD" ]; then
      SCRAPED_DATA=$(cat "$SCRAPE_MD")
      echo "✅ Scrape complete — loaded: scrapes/${SCRAPE_DOMAIN}/raw.md"
      SCRAPE_SKILL_SECTION="
## REAL BUSINESS DATA (scraped from $WEBSITE_URL)

The following data was automatically extracted from the client's existing website.
Use it to populate ALL sections of the page with accurate, real content.
Do NOT invent placeholder text where real data is available.

\`\`\`
$SCRAPED_DATA
\`\`\`

DATA USAGE RULES:
- Business name, tagline, nav structure → from scraped data
- Services/offerings → from scraped services list (or raw_text_sections if services is empty)
- About section → from scraped about text
- Contact info → use scraped address, phone, email exactly
- Social links → use scraped URLs verbatim
- Brand colors → base CSS palette on detected colors when available
- Brand font → if a font was detected, use it or a harmonious companion via Google Fonts
- Testimonials → from scraped testimonials (if any)
- Image alt text → reference scraped image descriptions for meaningful alt attributes
- NEVER hotlink scraped image URLs — use only the local assets/ files as always
"
    else
      echo "⚠️  Scrape failed or raw.md not found — continuing without scraped data"
    fi
  else
    echo "⚠️  Scrape script not found at $SCRAPE_SCRIPT — skipping"
  fi
  echo ""
fi

# 6. GENERATE HTML
SKILL_INSTRUCTION="frontend-design skill"
if [ -n "$WEBSITE_URL" ] && [ -n "$SCRAPED_DATA" ]; then
  SKILL_INSTRUCTION="frontend-clone skill (which extends frontend-design with real scraped data)"
fi

PROMPT="
You are an expert web designer using the ${SKILL_INSTRUCTION}.
PROJECT: Create a high-converting landing page for a local business.

LANGUAGE - CRITICAL:
$LANG_INSTRUCTION

BUSINESS DETAILS:
- Name: $BUSINESS_NAME
- Niche: $NICHE
- Address: $ADDRESS
- Contact: $CONTACT
$SCRAPE_SKILL_SECTION
DESIGN INSTRUCTIONS:
Create a landing page design for a local $NICHE company.
Use the ${SKILL_INSTRUCTION} to ensure distinctive, production-grade aesthetics.
Use typography and design style that works for this niche. 
Use icons from Font Awesome (CDN) instead of using emoji.
Include JavaScript for scroll animations, reveal effects, and interactivity.

REQUIRED SECTIONS:
$SECTION_NAMES

IMAGES - CRITICAL RULES:
The images are ALREADY PRE-GENERATED and sitting in the assets/ folder. Do NOT try to generate or create images yourself. Do NOT use the nano-banana-pro skill. Just REFERENCE the existing images.
- ALL images MUST use LOCAL relative paths from the assets/ folder.
- NEVER use external URLs (no unsplash.com, no placeholder services, no external CDNs for images).
- These exact files already exist and are ready to use:
  - assets/hero.webp (use for the hero section)
  - assets/gallery-1.webp (use for gallery/portfolio)
  - assets/gallery-2.webp (use for gallery/portfolio)
  - assets/workshop.webp (use for about/workspace section)
  - assets/detail.webp (use for detail/feature sections)
  - assets/process.webp (use for process/how-it-works section)
- Use with relative paths: src=\"assets/hero.webp\"
- Add descriptive alt text to every image.
- Use ALL 6 images in the HTML. Do not skip any.

DESIGN REQUIREMENTS:
- Choose distinctive typography (Google Fonts, not Inter/Roboto/Arial).
- Create a cohesive color palette fitting the $NICHE industry using CSS variables.
- Make it fully responsive with a mobile breakpoint at 768px.
- The nav/header MUST use flexbox: logo left, links center, CTA right.
- MUST include a working hamburger menu for mobile using a checkbox toggle pattern.
- Include hover effects and transitions on buttons, cards, and nav links.
- NEVER reference images that don't exist (no logo.png, no dummy.png, no avatar images).
  For testimonials, use Font Awesome quote icons and text only — no customer photos.
- Do NOT duplicate any section. Each of the 9 sections appears exactly ONCE.

SCROLL ANIMATIONS - REQUIRED:
Include this JavaScript in a <script> tag before </body>:
- IntersectionObserver-based scroll reveal (add class=\"reveal\" to each <section>)
- Sticky header shadow toggle on scroll
- Smooth scroll for anchor links
Do NOT link to external .js files. All JS goes inline.

INLINE STYLE BAN:
- NEVER use style=\"...\" attributes in HTML elements. ALL styling goes in style.css.

JAVASCRIPT RULE:
- NEVER use 'window' as a variable name in forEach, map, or any callback. Use 'el' or 'element'. Example: elements.forEach(el => { ... })

CDN LINKS RULE:
- When linking external resources (Font Awesome, Google Fonts, etc.), do NOT add integrity= or crossorigin= attributes. Just use a simple <link> tag with rel and href.
- Example: <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css\">

OUTPUT FORMAT - CRITICAL:
Your VERY FIRST character of output MUST be '<' (the start of <!DOCTYPE html>).
Do NOT output any explanation, commentary, thinking, font choices, color palettes, or preamble before the code.
Do NOT say what you are going to do. Just output the raw HTML directly.
Do NOT output anything after the closing </html> tag.
- Output ONLY the raw HTML5 content for index.html.
- Do NOT include any CSS in the HTML file. No <style> tags at all.
- All styling will go in a separate file. Link it with: <link rel=\"stylesheet\" href=\"style.css\">
- Set lang=\"$SITE_LANG\" on the <html> tag.
- Do not output markdown code blocks. Just raw HTML code.

STRICT SERVER-SIDE ENVIRONMENT RULES:
- NEVER use bash tools, git, or write to the filesystem directly.
- NEVER try to push or commit anything to GitHub or any other repository.
- You must ONLY return the raw text to standard output for the parent script to capture.
"

# Function to generate text with retry logic
# - Supports both Claude CLI and Gemini CLI (controlled by TEXT_ENGINE)
# - On final retry: switches to the OTHER engine as fallback
# - Detects truncated HTML and usage limit messages
# - Max 2 retries (3 total attempts)
generate_text_with_retry() {
  local prompt="$1"
  local output_file="$2"
  local label="$3"
  local max_retries=2
  local retry=0
  local success=false

  # Track the engine/model per attempt (may switch on fallback)
  local use_engine="$TEXT_ENGINE"
  local use_model="$TEXT_MODEL"

  while [ $retry -le $max_retries ]; do
    local err_file
    err_file=$(mktemp)

    # On retry 2: switch to the OTHER engine entirely
    if [ $retry -ge 2 ]; then
      if [ "$TEXT_ENGINE" = "claude" ]; then
        use_engine="gemini"
        use_model="gemini-2.5-flash"
      else
        use_engine="claude"
        use_model="sonnet"
      fi
      echo "     🔄 Switching to $use_engine ($use_model) for retry $retry..."
    fi

    # Verify the CLI is installed
    if ! command -v "$use_engine" &> /dev/null; then
      echo "     ❌ $use_engine command not found, cannot retry with fallback engine."
      if [ $retry -ge 2 ]; then
        echo "     ❌ ${label}: Failed — primary engine ($TEXT_ENGINE) exhausted, fallback ($use_engine) not installed."
        return 1
      fi
      # Skip to next retry (which will try the other engine)
      retry=$((retry + 1))
      continue
    fi

    # Dispatch to the correct CLI (with a 4-minute absolute timeout to prevent hanging)
    local cmd_ok=false
    if [ "$use_engine" = "claude" ]; then
      # --tools "" strictly disables Claude's ability to use Edit/Git/Bash, forcing raw stdout
      if printf "%s\\n" "$prompt" | timeout 240 claude -p --model "$use_model" --dangerously-skip-permissions --tools "" > "$output_file" 2> "$err_file"; then
        cmd_ok=true
      fi
    else
      if printf "%s\\n" "$prompt" | timeout 240 gemini -m "$use_model" -y -p "" > "$output_file" 2> "$err_file"; then
        cmd_ok=true
      fi
    fi

    if [ "$cmd_ok" = true ] && [ -s "$output_file" ]; then
      # Check for usage limit messages in the output itself
      # (Claude returns exit 0 but writes "You've hit your limit" as content)
      if grep -qi "hit your limit\|usage limit\|resets.*am\|exceeded.*limit" "$output_file" 2>/dev/null; then
        echo "     🛑 ${label}: $use_engine returned a usage limit message instead of content."
        echo "[WARN] Usage limit hit on attempt $((retry+1)) with $use_engine/$use_model" >> "$LOG_FILE"
        # Fall through to retry (will switch engine on retry 2)
      # For HTML generation: check for truncation (model hit output token limit)
      elif [ "$label" = "HTML" ] && ! grep -qi "</html" "$output_file"; then
        local trunc_size
        trunc_size=$(wc -c < "$output_file" 2>/dev/null || echo 0)
        echo "     ⚠️  ${label}: Output truncated ($(numfmt --to=iec $trunc_size 2>/dev/null || echo ${trunc_size}B), no </html>). Will retry."
        echo "[WARN] Truncated HTML on attempt $((retry+1)) with $use_engine/$use_model" >> "$LOG_FILE"
        # Fall through to retry
      else
        success=true
        rm -f "$err_file"
        break
      fi
    else
      if [ ! -s "$output_file" ]; then
        echo "Output file was empty (silent failure)" >> "$err_file"
      fi
    fi

    # Read error
    local err_content
    err_content=$(cat "$err_file")
    rm -f "$err_file"

    retry=$((retry + 1))
    if [ $retry -gt $max_retries ]; then
        echo "     ❌ ${label}: Failed after $max_retries retries (tried $TEXT_ENGINE + fallback)."
        echo "Error details: $err_content" >> "$LOG_FILE"
        return 1
    fi

    # Check for quota/rate limit errors
    if echo "$err_content" | grep -qi "MODEL_CAPACITY_EXHAUSTED\|429\|RESOURCE_EXHAUSTED\|rate_limit\|overloaded\|hit your limit\|exceeded.*limit"; then
        if [ $retry -lt 2 ]; then
          local wait=$((30 * retry))  # 30s, 60s
          echo "     ⏳ ${label}: Rate limited ($use_engine). Waiting ${wait}s before retry $retry/$max_retries..."
          sleep $wait
        else
          echo "     ⚠️  ${label}: $use_engine quota exhausted. Switching engine on next retry..."
        fi
    else
        echo "     ⚠️  ${label}: Error encountered ($use_engine). Retrying in 10s... ($retry/$max_retries)"
        echo "[WARN] Retry $retry for $label ($use_engine): $err_content" >> "$LOG_FILE"
        sleep 10
    fi
  done

  if [ "$success" = true ]; then
    return 0
  else
    return 1
  fi
}

echo "🔨 Generating index.html ($LANG_NAME)..."
echo "   [DEBUG] Tool: $TEXT_ENGINE | Model: $TEXT_MODEL"
echo "   [DEBUG] Prompt excerpt: ${PROMPT:0:80}..."
echo "   [DEBUG] Prompt length: ${#PROMPT} characters"
if ! generate_text_with_retry "$PROMPT" "$FOLDER_NAME/index.html" "HTML"; then
  echo "❌ Failed to generate HTML. See build.log."
  exit 1
fi

# Safely extract the actual HTML block, stripping all AI conversational preamble
python3 -c '
import sys
content = sys.stdin.read()
if "```html" in content:
    try:
        content = content.split("```html", 1)[1].split("```", 1)[0]
    except IndexError:
        pass
elif "<!DOCTYPE" in content:
    content = "<!DOCTYPE" + content.split("<!DOCTYPE", 1)[1]
elif "<html" in content:
    content = "<html" + content.split("<html", 1)[1]
# Remove trailing markdown ticks if any leaked out
content = content.replace("```", "")
print(content.strip())
' < "$FOLDER_NAME/index.html" > "$FOLDER_NAME/index.html.tmp" && mv "$FOLDER_NAME/index.html.tmp" "$FOLDER_NAME/index.html"

# Sanitize: remove integrity/crossorigin attrs (AI hallucinates bogus SHA hashes)
# and catch any runaway repeated content (e.g. "5F5F5F5F5F..." thousands of times)
# NOTE: Using a temp .py file to avoid bash/python quoting conflicts with regex.
SANITIZE_SCRIPT=$(mktemp /tmp/sanitize_XXXXXX.py)
cat > "$SANITIZE_SCRIPT" << 'PYEOF'
import re, sys

html = sys.stdin.read()
# Remove integrity="..." and crossorigin="..." attributes
html = re.sub(r'\s+integrity="[^"]*"', '', html)
html = re.sub(r'\s+crossorigin="[^"]*"', '', html)
# Detect and truncate any single character or short pattern repeated 100+ times
html = re.sub(r'(.{1,4})\1{100,}', '', html)
print(html)
PYEOF
python3 "$SANITIZE_SCRIPT" < "$FOLDER_NAME/index.html" > "$FOLDER_NAME/index.html.tmp" && mv "$FOLDER_NAME/index.html.tmp" "$FOLDER_NAME/index.html"
rm -f "$SANITIZE_SCRIPT"

HTML_SIZE=$(wc -c < "$FOLDER_NAME/index.html" 2>/dev/null || echo 0)
if [ "$HTML_SIZE" -eq 0 ]; then
  echo "❌ Error: index.html is empty after cleaning."
  exit 1
fi

echo "🔍 Verifying HTML integrity..."
if ! grep -qi "<html" "$FOLDER_NAME/index.html" || ! grep -qi "</html" "$FOLDER_NAME/index.html"; then
  echo "❌ Error: index.html is malformed or truncated (missing <html> or </html>)."
  exit 1
fi

HTML_SIZE_STR=$(numfmt --to=iec "$HTML_SIZE" 2>/dev/null || echo "${HTML_SIZE}B")
echo "✅ index.html created and validated! ($HTML_SIZE_STR)"

# 7. GENERATE CSS (fed with actual HTML for class name matching)
GENERATED_HTML=$(cat "$FOLDER_NAME/index.html")

CSS_PROMPT="
You are an expert CSS designer using the frontend-design skill.
Generate the complete CSS stylesheet for the HTML page below.

CRITICAL: Read the HTML carefully. Style EVERY class, ID, and element used in it.
You MUST match the EXACT class names and IDs from the HTML. Do not invent new ones.

DESIGN DIRECTION:
- This is a $NICHE business landing page for $BUSINESS_NAME.
- Use the frontend-design skill aesthetic guidelines.
- Choose distinctive typography (Google Fonts, not generic fonts).
- Create a cohesive color palette fitting the $NICHE industry.
- Add smooth animations, transitions, and micro-interactions.
- Make it fully responsive with mobile breakpoints.
- Use CSS variables for the color system.
- The nav/header must use flexbox: logo left, links center, CTA right — all on one horizontal line.
- Include hover effects and scroll-based animations.
- Make sure .reveal elements start visible, and any JS-driven animation classes only enhance them.

OUTPUT FORMAT - CRITICAL:
Your VERY FIRST character of output must be '@' (for @import) or ':' (for :root) or '/' (for a CSS comment).
Do NOT output any explanation, commentary, or preamble. Just raw CSS.
Do NOT wrap in markdown code blocks. Just the raw CSS code.
Include @import for Google Fonts at the top if needed.

STRICT SERVER-SIDE ENVIRONMENT RULES:
- NEVER use bash tools, git, or write to the filesystem directly.
- NEVER try to push or commit anything to GitHub or any other repository.
- You must ONLY return the raw text to standard output for the parent script to capture.

HERE IS THE HTML TO STYLE:
$GENERATED_HTML
"

echo "🎨 Generating style.css..."
echo "   [DEBUG] Tool: $TEXT_ENGINE | Model: $TEXT_MODEL"
echo "   [DEBUG] Prompt excerpt: ${CSS_PROMPT:0:80}..."
echo "   [DEBUG] Prompt length: ${#CSS_PROMPT} characters"
if ! generate_text_with_retry "$CSS_PROMPT" "$FOLDER_NAME/style.css" "CSS"; then
  echo "❌ Failed to generate CSS. See build.log."
  exit 1
fi

# Strip any AI preamble before actual CSS
if ! head -1 "$FOLDER_NAME/style.css" | grep -qE "^[@:\/\*\.]"; then
  sed -i -n '/^[@:\/\*\.#a-zA-Z]/,$p' "$FOLDER_NAME/style.css"
fi

CSS_SIZE=$(wc -c < "$FOLDER_NAME/style.css" 2>/dev/null || echo 0)
CSS_SIZE_STR=$(numfmt --to=iec "$CSS_SIZE" 2>/dev/null || echo "${CSS_SIZE}B")
echo "✅ style.css created! ($CSS_SIZE_STR)"

# 8. ALLOCATE SHORT ID
echo "🆔 Allocating short ID..."
SITE_ID="${SITE_ID:-}"  # Allow manual override via env var

if [ -f "$ID_MANAGER" ]; then
  if [ -n "$SITE_ID" ]; then
    # Manual: use the ID passed via env var
    ID_OUTPUT=$(uv run "$ID_MANAGER" assign \
        --id "$SITE_ID" \
        --business "$BUSINESS_NAME" \
        --remote-url "${REMOTE_SITE_URL:-}" 2>&1)
  else
    # Auto: allocate next available
    ID_OUTPUT=$(uv run "$ID_MANAGER" allocate \
        --business "$BUSINESS_NAME" \
        --remote-url "${REMOTE_SITE_URL:-}" 2>&1)
  fi

  # Parse output (key=value lines)
  SITE_ID=$(echo "$ID_OUTPUT" | grep '^SITE_ID=' | cut -d= -f2)
  SITE_URLID=$(echo "$ID_OUTPUT" | grep '^URLID=' | cut -d= -f2)

  if [ -n "$SITE_ID" ]; then
    echo "   ✅ Site ID: $SITE_ID"
    echo "   🔗 URLID:  $SITE_URLID"

    # Create preview wrapper HTML in sites/ root
    # This is an iframe wrapper with a "Claim Your Site" CTA banner.
    # The actual site (index.html / style.css) is NEVER modified — the banner
    # only appears when opening the short ID link (e.g. sites/42.html).
    # To remove: just share the direct slug URL instead of the ID link.

    # Language-aware claim bar copy + pre-filled contact URL
    # URL params land before #contact so texngo.it JS can read them via URLSearchParams
    # texngo.it contact form needs: document.querySelector('[name=name]').value = params.get('name') etc.
    BNAME_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$BUSINESS_NAME")
    if [ "$SITE_LANG" = "it" ]; then
      CLAIM_MSG="Questo sito generato con AI per <strong>$BUSINESS_NAME</strong> è riservato per <strong>48 ore</strong>. Clicca <em>Richiedi</em> per evitare la scadenza del link."
      CLAIM_BTN="🚀 Richiedi il Sito"
      MSG_ENC="S%C3%AC%2C+voglio+il+mio+sito+fatto+da+voi%21"  # "Sì, voglio il mio sito fatto da voi!"
    else
      CLAIM_MSG="This AI-generated site for <strong>$BUSINESS_NAME</strong> is reserved for <strong>48 hours</strong>. Click <em>Claim</em> to prevent link expiration."
      CLAIM_BTN="🚀 Claim Your Site"
      MSG_ENC="Yes%2C+I+want+my+website+done+by+you%21"
    fi
    CLAIM_URL="https://texngo.it/?name=${BNAME_ENC}&message=${MSG_ENC}&focus=email#contact"

    REDIRECT_FILE="sites/${SITE_ID}.html"
    cat > "$REDIRECT_FILE" <<REDIRECT_EOF
<!DOCTYPE html>
<html lang="$SITE_LANG">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview → $BUSINESS_NAME</title>
<style>
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; }
  body { display: flex; flex-direction: column; font-family: system-ui, sans-serif; background: #0f0f0f; }

  /* ── Claim bar ── */
  .claim-bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 20px;
    background: #111827;
    border-bottom: 1px solid #1f2937;
  }
  .claim-bar .label {
    font-size: 13px;
    color: #9ca3af;
    line-height: 1.4;
  }
  .claim-bar .label strong { color: #f3f4f6; }
  .claim-bar a.cta {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: #fff;
    font-weight: 700;
    font-size: 14px;
    padding: 9px 20px;
    border-radius: 8px;
    text-decoration: none;
    box-shadow: 0 2px 12px rgba(249,115,22,.4);
    transition: transform .15s, box-shadow .15s;
  }
  .claim-bar a.cta:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 18px rgba(249,115,22,.55);
  }
  .claim-bar a.cta svg { width: 15px; height: 15px; fill: currentColor; }

  /* ── Site iframe ── */
  iframe {
    flex: 1;
    width: 100%;
    border: none;
    display: block;
  }
</style>
</head>
<body>
  <div class="claim-bar">
    <p class="label">⏳ &nbsp;$CLAIM_MSG</p>
    <a class="cta" href="$CLAIM_URL" target="_blank" rel="noopener">
      $CLAIM_BTN
    </a>
  </div>
  <iframe src="${SITE_SLUG}/index.html" title="$BUSINESS_NAME preview"></iframe>
</body>
</html>
REDIRECT_EOF
    echo "   📄 Preview wrapper: $REDIRECT_FILE (iframe + Claim CTA → texngo.it/#contact)"
  else
    echo "   ⚠️  ID allocation returned no ID. Output: $ID_OUTPUT"
    SITE_ID=""
    SITE_URLID=""
  fi
else
  echo "   ⚠️  Skipping: id_manager.py not found"
  SITE_URLID=""
fi
echo ""

# 9. CALCULATE STATS
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

# Calculate total assets size
ASSETS_SIZE=$(du -sb "$FOLDER_NAME/assets" 2>/dev/null | cut -f1 || echo 0)
TOTAL_SIZE=$(du -sb "$FOLDER_NAME" 2>/dev/null | cut -f1 || echo 0)

# Cost estimation
OPENROUTER_IMG_COST=$(echo "${IMAGES_VIA_OPENROUTER:-0} * ${IMG_COST_EACH:-0}" | bc 2>/dev/null || echo "0")
# Format with leading zero if needed
OPENROUTER_IMG_COST=$(printf "%.3f" "$OPENROUTER_IMG_COST")

GEMINI_TEXT_COST="0.010"
if [ "$IMAGES_VIA_GEMINI" -gt 0 ]; then
  GEMINI_IMG_NOTE="(included in Google AI plan)"
else
  GEMINI_IMG_NOTE=""
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  📊 Build Stats"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  ⏱️  Total time:    ${MINUTES:-0}m ${SECONDS:-0}s"
echo "  🌐 Language:      ${LANG_NAME:-"Italian"} (${SITE_LANG:-"it"})"
echo "  🏗️  Mode:          $MODE  ($IMG_MODEL)"
echo ""
echo "  🖼️  Images:"
echo "     Generated:     $IMAGES_GENERATED / $IMG_TOTAL"
echo "     Failed:        $IMAGES_FAILED"
echo "     Via Gemini:    $IMAGES_VIA_GEMINI $GEMINI_IMG_NOTE"
echo "     Via OpenRouter: $IMAGES_VIA_OPENROUTER"
echo ""
echo "  📁 Files:"
echo "     Assets size:   $(numfmt --to=iec $ASSETS_SIZE 2>/dev/null || echo "${ASSETS_SIZE}B")"
echo "     Total size:    $(numfmt --to=iec $TOTAL_SIZE 2>/dev/null || echo "${TOTAL_SIZE}B")"
echo ""
echo "  💰 Estimated cost:"
if [ "$IMAGES_VIA_OPENROUTER" -gt 0 ]; then
  echo "     OpenRouter img: \$${OPENROUTER_IMG_COST} ($IMAGES_VIA_OPENROUTER × \$${IMG_COST_EACH})"
fi
if [ "$IMAGES_VIA_GEMINI" -gt 0 ]; then
  echo "     Gemini img:     included in plan ($IMAGES_VIA_GEMINI images)"
fi
echo "     Gemini text:    \$${GEMINI_TEXT_COST} (HTML + CSS generation)"
echo "     ─────────────"
TOTAL_COST=$(echo "$OPENROUTER_IMG_COST + $GEMINI_TEXT_COST" | bc 2>/dev/null || echo "0.010")
TOTAL_COST=$(printf "%.3f" "$TOTAL_COST")
echo "     Total:          \$${TOTAL_COST}"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📁 $FOLDER_NAME/"
echo "  ├── assets/"
echo "  │   ├── detail.webp"
echo "  │   ├── gallery-1.webp"
echo "  │   ├── gallery-2.webp"
echo "  │   ├── hero.webp"
echo "  │   ├── process.webp"
echo "  │   └── workshop.webp"
echo "  ├── index.html"
echo "  ├── style.css"
echo "  └── build.log"
echo ""
echo "  📋 Full log: $LOG_FILE"
echo ""

# Final URL output  — the 🌐 Open: line is used by test-all.py as a build-complete marker
if [ -n "$REMOTE_SITE_URL" ]; then
  SITE_PUBLIC_URL="$REMOTE_SITE_URL/$SITE_SLUG/index.html"
  echo "  🌐 URL=$SITE_PUBLIC_URL"
  if [ -n "$SITE_URLID" ]; then
    echo "  🆔 URLID=$SITE_URLID"
    echo "  🆔 SITE_ID=$SITE_ID"
  fi
  echo "  📂 Local: file://$SCRIPT_DIR/$FOLDER_NAME/index.html"
  
  echo -n "  📡 Testing remote live URL... "
  # Wait briefly for web server (Caddy/Nginx) to detect the new file
  sleep 1
  if curl -s -f -m 10 "$SITE_PUBLIC_URL" > /dev/null; then
    echo "[OK]"
  else
    echo "[ERROR] - URL not serving a 200 OK (Yet?)"
  fi
else
  SITE_PUBLIC_URL="N/A (Local build)"
  echo "  🌐 URL=open $FOLDER_NAME/index.html"
fi
echo ""

# The final call on success
send_build_summary "COMPLETE"
echo ""
# Clear trap on success
trap - EXIT