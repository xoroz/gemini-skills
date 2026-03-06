#!/bin/bash

# Usage: ./modify.sh "site-slug" "#hero-title" "Make it say welcome to the best place"

SITE_SLUG="$1"
SELECTOR="$2"
PROMPT="$3"

if [ -z "$SITE_SLUG" ] || [ -z "$SELECTOR" ] || [ -z "$PROMPT" ]; then
  echo "Usage: ./modify.sh <site-slug> <selector> <prompt>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SITE_DIR="$SCRIPT_DIR/sites/$SITE_SLUG"
INDEX_FILE="$SITE_DIR/index.html"

if [ ! -f "$INDEX_FILE" ]; then
  echo "❌ Error: index.html not found in $SITE_DIR"
  exit 1
fi

# 1. SETUP ENV (same as create.sh)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.npm-global/bin:$PATH"

if ! command -v gemini &> /dev/null; then
    NVM_BIN=$(ls -d $HOME/.nvm/versions/node/*/bin 2>/dev/null | tail -n1 || echo "")
    if [ -n "$NVM_BIN" ]; then export PATH="$NVM_BIN:$PATH"; fi
fi

if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^\s*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    if [ -z "${!key+x}" ]; then
      export "$line" 2>/dev/null || true
    fi
  done < "$SCRIPT_DIR/.env"
fi

TEXT_MODEL="${AI_MODEL_TEXT:-gemini-2.5-flash}"

# 2. Extract the element
echo "🔍 Extracting element '$SELECTOR' from $INDEX_FILE..."
EXTRACTED_HTML=$(uv run "$SCRIPT_DIR/scripts/modify_html.py" extract --file "$INDEX_FILE" --selector "$SELECTOR")

if [ $? -ne 0 ]; then
  echo "❌ Error: Could not extract element."
  exit 1
fi

echo "--- Original Element ------------------"
echo "$EXTRACTED_HTML"
echo "---------------------------------------"

# 3. Ask Gemini for the modified element
echo "🤖 Asking Gemini ($TEXT_MODEL) to modify the HTML..."

AI_PROMPT="
You are an expert web developer.
The user wants to modify a specific HTML element on their website.
Here is the original HTML element:
\`\`\`html
$EXTRACTED_HTML
\`\`\`

USER REQUEST:
$PROMPT

Please provide ONLY the modified HTML for this element. 
Do not wrap it in markdown ticks (\`\`\`html) in your response, just the raw HTML. 
Do not include any explanation. 
Keep the exact same ID and any classes unless the user specifically asked to change them.
"

OUTPUT_FILE=$(mktemp)
echo "$AI_PROMPT" | gemini -m "$TEXT_MODEL" -y -p "" > "$OUTPUT_FILE"

# Clean up any potential markdown ticks in the output
python3 -c '
import sys
content = sys.stdin.read()
if "```html" in content:
    try:
        content = content.split("```html", 1)[1].split("```", 1)[0]
    except IndexError:
        pass
content = content.replace("```", "")
print(content.strip())
' < "$OUTPUT_FILE" > "${OUTPUT_FILE}.tmp" && mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"

echo "--- Modified Element ------------------"
cat "$OUTPUT_FILE"
echo "---------------------------------------"

# 4. Inject the modified element back into index.html
echo "✨ Injecting new HTML back into index.html..."

uv run "$SCRIPT_DIR/scripts/modify_html.py" replace --file "$INDEX_FILE" --selector "$SELECTOR" --replacement "$OUTPUT_FILE"

if [ $? -ne 0 ]; then
  echo "❌ Error injecting new HTML."
  rm -f "$OUTPUT_FILE"
  exit 1
fi

rm -f "$OUTPUT_FILE"
echo "✅ Successfully modified $INDEX_FILE!"
