#!/bin/bash

# Usage: ./create.sh "Business Name" "Niche" "Address" "Contact Info"
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
    
    🖨️ Flyer    : assets/flyers/${FLYER_NAME:-"N/A"}
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
        echo "❌ Script failed with exit code $exit_code. Sending error email..."
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
        # Break out of retry loop but leave SUCCESS=false
        break
      fi

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

if [ "$IMAGES_FAILED" -gt 0 ]; then
  echo "❌ Error: $IMAGES_FAILED image(s) failed to generate correctly (or sizes were invalid). Aborting build."
  exit 1
fi


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

CDN LINKS RULE:
- When linking external resources (Font Awesome, Google Fonts, etc.), do NOT add integrity= or crossorigin= attributes. Just use a simple <link> tag with rel and href.
- Example: <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">

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

# Check for truncated output (model hit token limit — HTML cut off mid-tag)
if ! grep -qi "</html" "$FOLDER_NAME/index.html"; then
  if grep -qi "<html" "$FOLDER_NAME/index.html"; then
    echo "⚠️  HTML appears truncated (has <html> but no </html>). Model may have hit output token limit."
    echo "   File size: $(numfmt --to=iec "$HTML_SIZE" 2>/dev/null || echo "${HTML_SIZE}B") — appending closing tags as recovery."
    # Attempt a best-effort recovery by closing any open tags
    echo "</div></section></main></body></html>" >> "$FOLDER_NAME/index.html"
  else
    echo "❌ Error: index.html is severely malformed (missing root tags)."
    exit 1
  fi
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

# 9. GENERATE FLYER
MAKE_FLYER_SCRIPT="$SCRIPT_DIR/scripts/make_flyer.py"
FLYER_TEMPLATE="$SCRIPT_DIR/assets/template-flyer.png"
FLYER_NAME="flyer-${SITE_SLUG}.png"
FLYER_ASSETS_DIR="$SCRIPT_DIR/assets/flyers"
FLYER_ASSETS_OUT="$FLYER_ASSETS_DIR/$FLYER_NAME"
FLYER_SITE_OUT="$SCRIPT_DIR/$FOLDER_NAME/assets/$FLYER_NAME"

# Build the QR URL — use URLID (short redirect) if available, fall back to slug
if [ -n "$SITE_URLID" ]; then
  FLYER_QR_URL="$SITE_URLID"
elif [ -n "$REMOTE_SITE_URL" ]; then
  FLYER_QR_URL="$REMOTE_SITE_URL/$SITE_SLUG"
else
  FLYER_QR_URL="https://${SITE_SLUG}.texngo.it"
fi

echo "📄 Generating flyer..."
echo "   QR URL : $FLYER_QR_URL"

mkdir -p "$FLYER_ASSETS_DIR"

FLYER_ID_ARGS=()
if [ -n "$SITE_ID" ]; then
  FLYER_ID_ARGS=("--site-id" "$SITE_ID")
fi

if [ -f "$MAKE_FLYER_SCRIPT" ] && [ -f "$FLYER_TEMPLATE" ]; then
  if uv run "$MAKE_FLYER_SCRIPT" \
      --name     "$BUSINESS_NAME" \
      --url      "$FLYER_QR_URL" \
      --template "$FLYER_TEMPLATE" \
      --output   "$FLYER_ASSETS_OUT" \
      "${FLYER_ID_ARGS[@]}" 2>&1 | sed 's/^/   /'; then
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