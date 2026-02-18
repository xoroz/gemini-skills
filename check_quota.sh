#!/bin/bash
# Check if Gemini API is available and not rate-limited.
# Usage: ./check_quota.sh

echo "🔍 Checking Gemini API availability..."

OUTPUT=$(echo "Hello" | gemini -y -p "" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Gemini API is responding."
  echo "   Response: $OUTPUT"
  exit 0
else
  echo "❌ Gemini API failed."
  echo "   Exit code: $EXIT_CODE"
  echo "   Output: $OUTPUT"
  
  if echo "$OUTPUT" | grep -q "MODEL_CAPACITY_EXHAUSTED"; then
    echo "   ⚠️  QUOTA EXHAUSTED (Model Capacity)"
  elif echo "$OUTPUT" | grep -q "429"; then
    echo "   ⚠️  RATE LIMITED"
  fi
  exit 1
fi
