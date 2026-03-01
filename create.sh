#!/bin/bash

# Usage: ./create.sh "Business Name" "Niche" "Address" "Contact Info"
# Language: Set SITE_LANG=en before running to generate in English (default: it)
# Mode:     Set MODE=DEV for cheap/fast images (riverflow), MODE=PROD for quality (default: PROD)
#
# Examples:
#   ./create.sh "Officina Mario" "riparazione auto" "Via Roma 42, Milano" "+39 02 1234567"
#   SITE_LANG=en ./create.sh "Joe's Garage" "auto repair" "123 Main St" "555-1234"
#   MODE=DEV ./create.sh "Test Salon" "parrucchiere" "Via Test 1" "+39 000"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
    
    🖨️ Flyer    : assets/flyers/${FLYER_NAME:-"N/A"}
    ═══════════════════════════════════════════════
    Build log: ${LOG_FILE:-"N/A"} (attached if exists)
    "

    # Send via python utility
    local mail_args=("$from" "$to" "$subject" "$body")
    if [ -f "${LOG_FILE:-}" ]; then mail_args+=("$LOG_FILE"); fi

    uv run "$MAIL_SCRIPT" "${mail_args[@]}" | sed 's/^/   /'
    echo "✅ Email notification sent!"
  fi
}

on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "❌ Script failed with exit code $exit_code. Sending error email..."
        # Avoid trap loops
        trap - EXIT
        send_build_summary "FAILED"
    fi
}
trap on_error EXIT
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
# IMAGE MODEL & PRICING — edit these when rates change
# =============================================================================
MODE="${MODE:-DEV}"  # DEV = cheap/fast, PROD = quality, MOCKUP = skip billing

if [ "$MODE" = "DEV" ]; then
  IMG_MODEL="black-forest-labs/flux.2-klein-4b"
  IMG_COST_EACH=0.014
elif [ "$MODE" = "PROD" ]; then
  IMG_MODEL="google/gemini-2.5-flash-image"
  IMG_COST_EACH=0.038   # ~$0.030/img via OpenRouter
else
  IMG_MODEL="mockup (local .skel)"
  IMG_COST_EACH=0
fi

if [ "$MODE" = "DEV" ] || [ "$MODE" = "MOCKUP" ]; then
  TEXT_MODEL="gemini-2.5-flash-lite"
else
  TEXT_MODEL="gemini-2.5-flash"
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
SITE_SLUG=$(echo "$BUSINESS_NAME" | sed -e 's/ /-/g' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-')
FOLDER_NAME="sites/$SITE_SLUG"
LOG_FILE="$FOLDER_NAME/build.log"

mkdir -p "$FOLDER_NAME/assets"

# Start logging
exec > >(tee -a "$LOG_FILE") 2>&1

echo "═══════════════════════════════════════════════════"
echo "  🏗️  Landing Page Builder"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  📂 Business: $BUSINESS_NAME"
echo "  🏷️  Niche:    $NICHE"
echo "  📍 Address:  $ADDRESS"
echo "  📞 Contact:  $CONTACT"
echo "  🌐 Language: $LANG_NAME ($SITE_LANG)"
echo "  📁 Output:   $FOLDER_NAME/"
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
IMAGES["hero"]="Professional high-quality hero photograph for a $NICHE business called $BUSINESS_NAME. Showcase the main product or service in a dramatic, cinematic style with beautiful lighting. Premium commercial photography feel."
IMAGES["gallery-1"]="Professional gallery photograph for a $NICHE business. Showcase a completed project or product in pristine condition. Studio-quality lighting, clean background. Commercial photography."
IMAGES["gallery-2"]="Professional gallery photograph for a $NICHE business. Different angle or product than the first gallery image. Beautiful detail shot with dramatic lighting. High-end commercial photography."
IMAGES["workshop"]="Interior photograph of a professional $NICHE workshop or workspace. Clean, organized, well-lit environment showing tools and equipment. Professional commercial photography."
IMAGES["detail"]="Close-up detail photograph relevant to $NICHE. Macro shot showing craftsmanship, quality materials, or intricate work. Professional product photography with shallow depth of field."
IMAGES["process"]="Action photograph showing the $NICHE work process. Skilled hands at work, step-by-step craftsmanship in progress. Documentary-style commercial photography with warm lighting."

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

  while [ $RETRY -le $MAX_RETRIES ]; do
    OUTPUT=$(uv run "$IMAGE_SCRIPT" \
      --prompt "$IMG_PROMPT" \
      --output "$IMG_PATH" \
      --aspect landscape \
      --quality draft \
      --model "$IMG_MODEL" 2>&1)
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
      echo "$OUTPUT" | sed 's/^/     /'
      SUCCESS=true
      IMAGES_GENERATED=$((IMAGES_GENERATED + 1))
      # Track which provider was used
      if echo "$OUTPUT" | grep -q "\[openrouter\]"; then
        IMAGES_VIA_OPENROUTER=$((IMAGES_VIA_OPENROUTER + 1))
      else
        IMAGES_VIA_GEMINI=$((IMAGES_VIA_GEMINI + 1))
      fi
      break
    fi

    # Check if it's a rate limit error (429)
    if echo "$OUTPUT" | grep -q "429\|RESOURCE_EXHAUSTED\|rate"; then
      RETRY=$((RETRY + 1))
      if [ $RETRY -le $MAX_RETRIES ]; then
        WAIT=$((30 * RETRY))  # 30s, 60s backoff
        echo "     ⏳ Rate limited. Waiting ${WAIT}s before retry $RETRY/$MAX_RETRIES..."
        sleep $WAIT
      else
        echo "     ❌ Failed after $MAX_RETRIES retries (rate limited)."
      fi
    else
      # Non-rate-limit error, don't retry
      echo "$OUTPUT" | sed 's/^/     /'
      echo "  ⚠️  Warning: Failed to generate ${IMG_NAME}.png, continuing..."
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

# 6. GENERATE HTML
PROMPT="
You are an expert web designer using the frontend-design skill.
PROJECT: Create a high-converting landing page for a local business.

LANGUAGE - CRITICAL:
$LANG_INSTRUCTION

BUSINESS DETAILS:
- Name: $BUSINESS_NAME
- Niche: $NICHE
- Address: $ADDRESS
- Contact: $CONTACT

DESIGN INSTRUCTIONS:
Create a landing page design for a local $NICHE company. 
Use the frontend-design skill to ensure distinctive, production-grade aesthetics.
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
  - assets/hero.png (use for the hero section)
  - assets/gallery-1.png (use for gallery/portfolio)
  - assets/gallery-2.png (use for gallery/portfolio)
  - assets/workshop.png (use for about/workspace section)
  - assets/detail.png (use for detail/feature sections)
  - assets/process.png (use for process/how-it-works section)
- Use with relative paths: src=\"assets/hero.png\"
- Add descriptive alt text to every image.
- Use ALL 6 images in the HTML. Do not skip any.

DESIGN REQUIREMENTS:
- Choose distinctive typography (Google Fonts, not generic fonts).
- Create a cohesive color palette fitting the $NICHE industry.
- Add smooth animations and micro-interactions.
- Make it fully responsive with mobile breakpoints.
- Use CSS variables for the color system.
- The nav/header must use flexbox: logo left, links center, CTA button right — all on one horizontal line.
- Include hover effects, transitions, and scroll-based animations.

JAVASCRIPT RULE:
- NEVER use 'window' as a variable name in forEach, map, or any callback. Use 'el' or 'element'. Example: elements.forEach(el => { ... })

OUTPUT FORMAT - CRITICAL:
Your VERY FIRST character of output MUST be '<' (the start of <!DOCTYPE html>).
Do NOT output any explanation, commentary, thinking, or preamble before the code.
Do NOT say what you are going to do. Just output the raw HTML directly.
- Output ONLY the raw HTML5 content for index.html.
- Do NOT include any CSS in the HTML file. No <style> tags at all.
- All styling will go in a separate file. Link it with: <link rel=\"stylesheet\" href=\"style.css\">
- Set lang=\"$SITE_LANG\" on the <html> tag.
- Do not output markdown code blocks. Just raw HTML code.
"

# Function to generate text with retry logic for rate limits
generate_text_with_retry() {
  local prompt="$1"
  local output_file="$2"
  local label="$3"
  local max_retries=3
  local retry=0
  local success=false

  while [ $retry -le $max_retries ]; do
    # Create temp file for stderr to catch errors without mixing with stdout
    local err_file
    err_file=$(mktemp)

    # Run gemini, redirecting stderr to temp file
    if ! command -v gemini &> /dev/null; then
      echo "❌ Error: gemini command not found in PATH." > "$err_file"
      return 1
    fi

    if echo "$prompt" | gemini -m "$TEXT_MODEL" -y -p "" > "$output_file" 2> "$err_file"; then
      # Success? Check if the file is empty (sometimes gemini fails silently)
      if [ -s "$output_file" ]; then
        success=true
        rm -f "$err_file"
        break
      else
        echo "Output file was empty (silent failure)" >> "$err_file"
      fi
    fi

    # Read error
    local err_content
    err_content=$(cat "$err_file")
    rm -f "$err_file"

    retry=$((retry + 1))
    if [ $retry -gt $max_retries ]; then
        echo "     ❌ ${label}: Failed after $max_retries retries."
        echo "Error details: $err_content" >> "$LOG_FILE"
        return 1
    fi

    # Check for quota/rate limit errors
    if echo "$err_content" | grep -q "MODEL_CAPACITY_EXHAUSTED\|429\|RESOURCE_EXHAUSTED"; then
        local wait=$((60 * retry))  # 60s, 120s, 180s
        echo "     ⏳ ${label}: Rate limited (Capacity Exhausted). Waiting ${wait}s before retry $retry/$max_retries..."
        sleep $wait
    else
        # Generic error (network blip, empty response, etc)
        echo "     ⚠️  ${label}: Error encountered. Retrying in 10s... ($retry/$max_retries)"
        # Log incident but keep going
        echo "[WARN] Retry $retry for $label: $err_content" >> "$LOG_FILE"
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
if ! generate_text_with_retry "$PROMPT" "$FOLDER_NAME/index.html" "HTML"; then
  echo "❌ Failed to generate HTML. See build.log."
  exit 1
fi

# Strip any AI preamble before <!DOCTYPE
if ! head -1 "$FOLDER_NAME/index.html" | grep -q "<!DOCTYPE"; then
  sed -i -n '/<!DOCTYPE/,$p' "$FOLDER_NAME/index.html"
fi

HTML_SIZE=$(wc -c < "$FOLDER_NAME/index.html" 2>/dev/null || echo 0)
if [ "$HTML_SIZE" -eq 0 ]; then
  echo "❌ Error: index.html is empty after cleaning."
  exit 1
fi

HTML_SIZE_STR=$(numfmt --to=iec "$HTML_SIZE" 2>/dev/null || echo "${HTML_SIZE}B")
echo "✅ index.html created! ($HTML_SIZE_STR)"

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

HERE IS THE HTML TO STYLE:
$GENERATED_HTML
"

echo "🎨 Generating style.css..."
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

# 8. GENERATE FLYER
MAKE_FLYER_SCRIPT="$SCRIPT_DIR/scripts/make_flyer.py"
FLYER_TEMPLATE="$SCRIPT_DIR/assets/template-flyer.png"
FLYER_NAME="flyer-${SITE_SLUG}.png"
FLYER_ASSETS_DIR="$SCRIPT_DIR/assets/flyers"
FLYER_ASSETS_OUT="$FLYER_ASSETS_DIR/$FLYER_NAME"
FLYER_SITE_OUT="$SCRIPT_DIR/$FOLDER_NAME/assets/$FLYER_NAME"

# Build the preview URL for the QR code
if [ -n "$REMOTE_SITE_URL" ]; then
  FLYER_QR_URL="$REMOTE_SITE_URL/$SITE_SLUG"
else
  FLYER_QR_URL="https://${SITE_SLUG}.texngo.it"
fi

echo "📄 Generating flyer..."
echo "   QR URL : $FLYER_QR_URL"

mkdir -p "$FLYER_ASSETS_DIR"

if [ -f "$MAKE_FLYER_SCRIPT" ] && [ -f "$FLYER_TEMPLATE" ]; then
  if uv run "$MAKE_FLYER_SCRIPT" \
      --name     "$BUSINESS_NAME" \
      --url      "$FLYER_QR_URL" \
      --template "$FLYER_TEMPLATE" \
      --output   "$FLYER_ASSETS_OUT" 2>&1 | sed 's/^/   /'; then
    # Copy into the site's assets folder too
    cp "$FLYER_ASSETS_OUT" "$FLYER_SITE_OUT"
    echo "   📋 Also saved → $FOLDER_NAME/assets/$FLYER_NAME"
    echo "✅ Flyer ready!"
  else
    echo "⚠️  Flyer generation failed — site is still complete."
  fi
else
  [ ! -f "$MAKE_FLYER_SCRIPT" ] && echo "⚠️  Skipping flyer: make_flyer.py not found"
  [ ! -f "$FLYER_TEMPLATE" ]    && echo "⚠️  Skipping flyer: template-flyer.png not found"
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
echo "  │   ├── detail.png"
echo "  │   ├── gallery-1.png"
echo "  │   ├── gallery-2.png"
echo "  │   ├── hero.png"
echo "  │   ├── process.png"
echo "  │   ├── workshop.png"
echo "  │   └── $FLYER_NAME"
echo "  ├── index.html"
echo "  ├── style.css"
echo "  └── build.log"
echo ""
echo "  🖨️  Flyer (global): assets/flyers/$FLYER_NAME"
echo ""
echo "  📋 Full log: $LOG_FILE"
echo ""

# Final URL output  — the 🌐 Open: line is used by test-all.py as a build-complete marker
if [ -n "$REMOTE_SITE_URL" ]; then
  SITE_PUBLIC_URL="$REMOTE_SITE_URL/$SITE_SLUG/index.html"
  echo "  🌐 Open: $SITE_PUBLIC_URL"
  echo "  📂 Local: file://$SCRIPT_DIR/$FOLDER_NAME/index.html"
else
  SITE_PUBLIC_URL="N/A (Local build)"
  echo "  🌐 Open: open $FOLDER_NAME/index.html"
fi
echo ""

# The final call on success
send_build_summary "COMPLETE"
echo ""
# Clear trap on success
trap - EXIT