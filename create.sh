#!/bin/bash

# Usage: ./create.sh "Business Name" "Niche" "Address" "Contact Info"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_SCRIPT="$SCRIPT_DIR/skills/nano-banana-pro/scripts/image.py"

# 1. READ INPUTS
BUSINESS_NAME="$1"
NICHE="$2"
ADDRESS="$3"
CONTACT="$4"

# Validate inputs
if [ -z "$BUSINESS_NAME" ] || [ -z "$NICHE" ]; then
  echo "❌ Error: Missing arguments."
  echo "Usage: ./create.sh \"Business Name\" \"Niche\" \"Address\" \"Contact Info\""
  exit 1
fi

# Check GEMINI_API_KEY
if [ -z "$GEMINI_API_KEY" ]; then
  echo "❌ Error: GEMINI_API_KEY environment variable not set."
  exit 1
fi

# 2. CREATE FOLDER STRUCTURE
# Convert "Joe's Garage" to "joes-garage"
FOLDER_NAME=$(echo "$BUSINESS_NAME" | sed -e 's/ /-/g' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-')

echo "📂 Creating site for: $BUSINESS_NAME ($NICHE)"
echo "📍 Location: $ADDRESS"
mkdir -p "$FOLDER_NAME/assets"

# 3. GENERATE LOCAL IMAGES WITH NANO-BANANA-PRO
echo ""
echo "🎨 Generating images with Nano Banana Pro..."
echo ""

declare -A IMAGES
IMAGES["hero-car"]="Professional high-quality hero photograph for a $NICHE business called $BUSINESS_NAME. Showcase the main product or service in a dramatic, cinematic style with beautiful lighting. Premium commercial photography feel."
IMAGES["gallery-mustang"]="Professional gallery photograph for a $NICHE business. Showcase a completed project or product in pristine condition. Studio-quality lighting, clean background. Commercial photography."
IMAGES["gallery-jaguar"]="Professional gallery photograph for a $NICHE business. Different angle or product than the first gallery image. Beautiful detail shot with dramatic lighting. High-end commercial photography."
IMAGES["workshop"]="Interior photograph of a professional $NICHE workshop or workspace. Clean, organized, well-lit environment showing tools and equipment. Professional commercial photography."
IMAGES["interior-detail"]="Close-up detail photograph relevant to $NICHE. Macro shot showing craftsmanship, quality materials, or intricate work. Professional product photography with shallow depth of field."
IMAGES["restoration-process"]="Action photograph showing the $NICHE work process. Skilled hands at work, step-by-step craftsmanship in progress. Documentary-style commercial photography with warm lighting."

IMG_COUNT=0
IMG_TOTAL=${#IMAGES[@]}

for IMG_NAME in "${!IMAGES[@]}"; do
  IMG_COUNT=$((IMG_COUNT + 1))
  IMG_PATH="$FOLDER_NAME/assets/${IMG_NAME}.png"
  IMG_PROMPT="${IMAGES[$IMG_NAME]}"
  
  echo "  🖼️  [$IMG_COUNT/$IMG_TOTAL] Generating: assets/${IMG_NAME}.png"
  
  # Retry loop with exponential backoff for rate limits
  MAX_RETRIES=3
  RETRY=0
  SUCCESS=false
  
  while [ $RETRY -le $MAX_RETRIES ]; do
    OUTPUT=$(uv run "$IMAGE_SCRIPT" \
      --prompt "$IMG_PROMPT" \
      --output "$IMG_PATH" \
      --aspect landscape \
      --quality draft 2>&1)
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
      echo "$OUTPUT" | sed 's/^/     /'
      SUCCESS=true
      break
    fi
    
    # Check if it's a rate limit error (429)
    if echo "$OUTPUT" | grep -q "429\|RESOURCE_EXHAUSTED\|rate"; then
      RETRY=$((RETRY + 1))
      if [ $RETRY -le $MAX_RETRIES ]; then
        WAIT=$((30 * RETRY))  # 30s, 60s, 90s backoff
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
    echo "  ⚠️  Warning: Could not generate ${IMG_NAME}.png, continuing..."
  fi
  
  # Delay between requests to avoid hitting rate limits
  if [ $IMG_COUNT -lt $IMG_TOTAL ]; then
    echo "     ⏱️  Waiting 10s before next image (rate limit protection)..."
    sleep 10
  fi
done

echo ""
echo "✅ Images generated!"
echo ""

# 4. DEFINE THE PROMPT FOR HTML + CSS
PROMPT="
You are an expert web designer using the frontend-design skill.
PROJECT: Create a high-converting landing page for a local business.

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

REQUIRED SECTIONS:
1. Header/Nav (Sticky)
2. Hero (Compelling headline for $BUSINESS_NAME)
3. Services/Experiences
4. Recent Work/Gallery
5. About/History
6. Our Process
7. Testimonials
8. Contact Info with Form (Include address: $ADDRESS and contact: $CONTACT)
9. Footer

IMAGES - CRITICAL RULES:
- ALL images MUST use LOCAL paths from the assets/ folder.
- NEVER use external URLs (no unsplash.com, no placeholder services, no external CDNs for images).
- The following local images are available in the assets/ folder:
  - assets/hero-car.png (use for the hero section)
  - assets/gallery-mustang.png (use for gallery/portfolio)
  - assets/gallery-jaguar.png (use for gallery/portfolio)
  - assets/workshop.png (use for about/workspace section)
  - assets/interior-detail.png (use for detail/feature sections)
  - assets/restoration-process.png (use for process/how-it-works section)
- Use these images with relative paths: src=\"assets/hero-car.png\"
- Add descriptive alt text to every image.

TECHNICAL OUTPUT RULES:
- Output ONLY the raw HTML5 content for index.html.
- Do NOT include any CSS in the HTML file. No <style> tags.
- All CSS will go in a separate file. Link it with: <link rel=\"stylesheet\" href=\"style.css\">
- Make it responsive and mobile-friendly.
- Do not output markdown code blocks (like \`\`\`html), just the raw HTML code.
"

# 5. GENERATE HTML
echo "🔨 Generating index.html..."
echo "$PROMPT" | gemini -y -p "" > "$FOLDER_NAME/index.html"
echo "✅ index.html created!"

# 6. GENERATE CSS
CSS_PROMPT="
You are an expert CSS designer using the frontend-design skill.
Generate the complete CSS stylesheet for a $NICHE business landing page for $BUSINESS_NAME.

The HTML uses these sections: header/nav (sticky), hero, services, gallery, about, process, testimonials, contact form, footer.
Images use local paths like: assets/hero-car.png

DESIGN DIRECTION:
- Use the frontend-design skill aesthetic guidelines.
- Choose distinctive typography (Google Fonts, not generic fonts).
- Create a cohesive color palette fitting the $NICHE industry.
- Add smooth animations and micro-interactions.
- Make it fully responsive with mobile breakpoints.
- Use CSS variables for the color system.
- Include hover effects, transitions, and scroll-based animations.

TECHNICAL OUTPUT RULES:
- Output ONLY raw CSS code. No HTML, no markdown code blocks.
- This goes in style.css, linked from index.html.
- Include @import for Google Fonts at the top if needed.
- Do not wrap in \`\`\`css blocks, just the raw CSS.
"

echo "🎨 Generating style.css..."
echo "$CSS_PROMPT" | gemini -y -p "" > "$FOLDER_NAME/style.css"
echo "✅ style.css created!"

echo ""
echo "🎉 Done! Website created in: ./$FOLDER_NAME/"
echo ""
echo "   📁 $FOLDER_NAME/"
echo "   ├── assets/"
echo "   │   ├── gallery-jaguar.png"
echo "   │   ├── gallery-mustang.png"
echo "   │   ├── hero-car.png"
echo "   │   ├── interior-detail.png"
echo "   │   ├── restoration-process.png"
echo "   │   └── workshop.png"
echo "   ├── index.html"
echo "   └── style.css"
echo ""
echo "   Open with: open $FOLDER_NAME/index.html"