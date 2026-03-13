#!/usr/bin/env python3
"""
Generate 6 contextual image prompts from scraped business data.

Uses the Gemini REST API (GEMINI_API_KEY) as primary, OpenRouter as fallback.
No external libraries required — stdlib urllib only.

Reads scrapes/<domain>/data.json + raw.md, calls a fast/cheap text model to
produce 6 highly specific image prompts tailored to the actual business niche,
brand colors, and services.

Output: shell-sourceable variable assignments (stdout):
  SMART_IMG_HERO='...'
  SMART_IMG_GALLERY_1='...'
  SMART_IMG_GALLERY_2='...'
  SMART_IMG_WORKSHOP='...'
  SMART_IMG_DETAIL='...'
  SMART_IMG_PROCESS='...'

Usage:
  python scripts/generate_image_prompts.py \\
      --data-json scrapes/www.example.com/data.json \\
      --raw-md    scrapes/www.example.com/raw.md \\
      [--model    gemini-2.0-flash-lite]

Exit 0 on success, 1 on failure (create.sh falls back to generic prompts).
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

IMAGE_KEYS = ["hero", "gallery-1", "gallery-2", "workshop", "detail", "process"]

VAR_MAP = {
    "hero":      "SMART_IMG_HERO",
    "gallery-1": "SMART_IMG_GALLERY_1",
    "gallery-2": "SMART_IMG_GALLERY_2",
    "workshop":  "SMART_IMG_WORKSHOP",
    "detail":    "SMART_IMG_DETAIL",
    "process":   "SMART_IMG_PROCESS",
}

SYSTEM_PROMPT = (
    "You are a professional commercial photographer and AI image prompt engineer. "
    "Your task: given real business data, write 6 highly specific, cinematic image "
    "prompts for a landing page. Each prompt must reflect the actual business type, "
    "services, and brand identity — no generic placeholders. "
    "Return ONLY a valid JSON object with exactly these 6 keys: "
    "hero, gallery-1, gallery-2, workshop, detail, process. "
    "Each value is a single image generation prompt string (60-180 characters). "
    "Be concrete and visual — focus on the specific niche, real services, "
    "and brand aesthetic."
)


def build_user_prompt(data: dict, raw_md: str) -> str:
    meta     = data.get("metadata", {})
    branding = data.get("branding", {})
    content  = data.get("content", {})
    colors   = branding.get("color_palette", {})

    parts = []
    if meta.get("title"):
        parts.append(f"Business: {meta['title']}")
    if meta.get("description"):
        parts.append(f"Description: {meta['description']}")
    primary = colors.get("primary", [])
    if primary:
        parts.append(f"Brand colors: {', '.join(primary)}")
    fonts = branding.get("typography", [])
    if fonts:
        parts.append(f"Typography: {', '.join(fonts)}")
    h1 = content.get("h1_headings", [])
    if h1:
        parts.append(f"H1: {' | '.join(h1)}")
    h2 = content.get("h2_headings", [])[:5]
    if h2:
        parts.append(f"H2: {' | '.join(h2)}")

    parts.append("\n--- Scraped summary (first 1500 chars) ---")
    parts.append(raw_md[:1500])
    parts.append(
        "\nGenerate 6 image prompts as a JSON object with keys: "
        "hero, gallery-1, gallery-2, workshop, detail, process."
    )
    return "\n".join(parts)


def extract_json(text: str) -> dict:
    """Parse JSON from model output, handling markdown fences."""
    text = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text)


def call_gemini(user_content: str, model: str, api_key: str) -> dict:
    """Call Gemini REST API (generativelanguage.googleapis.com)."""
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_content
    payload = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 900,
            "temperature": 0.75,
        },
    }).encode()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        result = json.loads(resp.read())

    raw = result["candidates"][0]["content"]["parts"][0]["text"]
    return extract_json(raw)


def call_openrouter(user_content: str, model: str, api_key: str) -> dict:
    """Call OpenRouter API (fallback)."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 900,
        "temperature": 0.75,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization":  f"Bearer {api_key}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   "https://github.com/xoroz/gemini-skills",
            "X-Title":        "gemini-skills image prompt generator",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        result = json.loads(resp.read())

    raw = result["choices"][0]["message"]["content"]
    return extract_json(raw)


def shell_quote(s: str) -> str:
    """Escape a value for single-quoted shell assignment."""
    return s.replace("'", "'\\''")


def main():
    parser = argparse.ArgumentParser(
        description="Generate smart image prompts from scraped business data"
    )
    parser.add_argument("--data-json", required=True, help="Path to data.json")
    parser.add_argument("--raw-md",    required=True, help="Path to raw.md")
    parser.add_argument(
        "--model",
        default="",
        help="Model override (default: gemini-2.0-flash-lite via Gemini API, "
             "or openai/gpt-4o-mini via OpenRouter if no GEMINI_API_KEY)",
    )
    args = parser.parse_args()

    gemini_key    = os.environ.get("GEMINI_API_KEY", "")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

    if not gemini_key and not openrouter_key:
        print("ERROR: neither GEMINI_API_KEY nor OPENROUTER_API_KEY is set", file=sys.stderr)
        sys.exit(1)

    data_path   = Path(args.data_json)
    raw_md_path = Path(args.raw_md)

    if not data_path.exists():
        print(f"ERROR: data.json not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    data   = json.loads(data_path.read_text(encoding="utf-8"))
    raw_md = raw_md_path.read_text(encoding="utf-8") if raw_md_path.exists() else ""

    user_prompt = build_user_prompt(data, raw_md)

    prompts = None
    last_err = None

    # Primary: Gemini API
    if gemini_key:
        gemini_model = args.model if args.model and "/" not in args.model else "gemini-2.0-flash-lite"
        try:
            prompts = call_gemini(user_prompt, gemini_model, gemini_key)
            print(f"# model: {gemini_model} (Gemini API)", file=sys.stderr)
        except Exception as e:
            last_err = e
            print(f"WARNING: Gemini call failed ({e}), trying OpenRouter...", file=sys.stderr)

    # Fallback: OpenRouter
    if prompts is None and openrouter_key:
        or_model = args.model if args.model else "openai/gpt-4o-mini"
        try:
            prompts = call_openrouter(user_prompt, or_model, openrouter_key)
            print(f"# model: {or_model} (OpenRouter)", file=sys.stderr)
        except Exception as e:
            last_err = e

    if prompts is None:
        print(f"ERROR: all API calls failed. Last error: {last_err}", file=sys.stderr)
        sys.exit(1)

    # Validate we got all 6 keys
    missing = [k for k in IMAGE_KEYS if not prompts.get(k)]
    if missing:
        print(f"ERROR: missing keys in response: {missing}", file=sys.stderr)
        sys.exit(1)

    # Output shell-sourceable assignments
    for key, var in VAR_MAP.items():
        val = str(prompts.get(key, "")).strip()
        if val:
            print(f"{var}='{shell_quote(val)}'")


if __name__ == "__main__":
    main()
