#!/usr/bin/env python3
"""score_site.py — Visual UX scorer for landing pages.

Takes a screenshot (or renders a local HTML / live URL) and scores it using
OpenRouter with a vision-capable model. No external libraries — stdlib only
(same pattern as generate_image_prompts.py).

Output JSON:
  {
    "vote": 7,
    "notes": ["hero overlay is clean", "nav CTA missing", "fonts readable"],
    "improvements": ["add dark overlay to hero", "replace lorem ipsum in services", "add phone to footer"]
  }

Usage:
  uv run scripts/score_site.py --screenshot path/to/shot.png [--out score.json]
  uv run scripts/score_site.py --html path/to/index.html [--out score.json]
  uv run scripts/score_site.py --url https://example.com [--out score.json]

Requires: OPENROUTER_API_KEY in environment or .env
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load .env so the script works standalone (outside FastAPI)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"

SCORE_PROMPT = """You are a professional UX reviewer auditing a website screenshot.

Return ONLY a valid JSON object with exactly these 3 keys, no commentary:
{
  "vote": <integer 0-10>,
  "notes": ["<line 1>", "<line 2>", "<line 3>"],
  "improvements": ["<line 1>", "<line 2>", "<line 3>"]
}

Scoring rules:
- vote: 0 = completely broken/unstyled, 5 = mediocre but functional, 8 = good, 10 = excellent
- notes: up to 3 short lines — describe what you observe (good or bad).
  Look for: hero text unreadable over image, missing dark overlay, broken layout,
  empty/placeholder sections, lorem ipsum, unreadable text colors, nav overflow,
  CSS not loaded, missing images, elements overlapping.
- improvements: up to 3 specific actionable lines for a designer rebuilding this site.
  Examples: "add semi-transparent dark overlay to hero image", "increase body font contrast",
  "replace placeholder text in services section with real content".

Be strict. Be concise. Return JSON only."""


# ---------------------------------------------------------------------------
# Screenshot helpers (Playwright)
# ---------------------------------------------------------------------------

def take_screenshot(html_path: Path, output_path: Path) -> None:
    """Render a local HTML file to PNG at 1280×900 viewport."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output_path))
        browser.close()


def take_url_screenshot(url: str, output_path: Path) -> None:
    """Screenshot a live URL at 1280×900 viewport."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output_path))
        browser.close()


# ---------------------------------------------------------------------------
# OpenRouter vision call
# ---------------------------------------------------------------------------

def call_openrouter(image_path: Path, model: str, api_key: str) -> dict:
    """Send a screenshot to an OpenRouter vision model and return the raw dict."""
    suffix = image_path.suffix.lower()
    media_map = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")

    with open(image_path, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    payload = json.dumps({
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                    {"type": "text", "text": SCORE_PROMPT},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 512,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://github.com/xoroz/gemini-skills",
            "X-Title":       "gemini-skills site scorer",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    raw = result["choices"][0]["message"]["content"]
    return extract_json(raw)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Parse JSON from model output, handling markdown fences and extra prose."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Fall back: grab the outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    return json.loads(text)


def validate(data: dict) -> dict:
    """Coerce the model response into a clean, guaranteed-schema dict."""
    # vote: must be int 0-10
    try:
        vote = max(0, min(10, int(float(str(data.get("vote", 5))))))
    except (ValueError, TypeError):
        vote = 5

    def to_list(val: object, limit: int = 3) -> list:
        if isinstance(val, list):
            return [str(x).strip() for x in val[:limit] if str(x).strip()]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    return {
        "vote":         vote,
        "notes":        to_list(data.get("notes",        [])),
        "improvements": to_list(data.get("improvements", [])),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Score a site screenshot via OpenRouter vision")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--screenshot", help="Path to existing screenshot (PNG/WebP/JPG)")
    group.add_argument("--html",       help="Path to index.html — rendered to screenshot first")
    group.add_argument("--url",        help="Live URL — screenshotted first")
    parser.add_argument("--out",   help="Write JSON to this path (also printed to stdout)")
    parser.add_argument("--label", default="site", help="Label: 'original', 'generated', etc.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"OpenRouter model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("[score] ERROR: OPENROUTER_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    tmp_screenshot: Optional[Path] = None

    if args.screenshot:
        screenshot_path = Path(args.screenshot)
    elif args.html:
        html_path       = Path(args.html)
        tmp_screenshot  = html_path.parent / "_score_tmp.png"
        print(f"[score] Rendering {html_path} ...", file=sys.stderr)
        take_screenshot(html_path, tmp_screenshot)
        screenshot_path = tmp_screenshot
    else:
        tmp_screenshot  = Path("/tmp/_score_url.png")
        print(f"[score] Screenshotting {args.url} ...", file=sys.stderr)
        take_url_screenshot(args.url, tmp_screenshot)
        screenshot_path = tmp_screenshot

    if not screenshot_path.exists():
        print(f"[score] ERROR: screenshot not found: {screenshot_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[score] Scoring via OpenRouter ({args.model}) ...", file=sys.stderr)
    try:
        raw    = call_openrouter(screenshot_path, args.model, api_key)
        result = validate(raw)
    except Exception as exc:
        print(f"[score] ERROR: {exc}", file=sys.stderr)
        if tmp_screenshot and tmp_screenshot.exists():
            tmp_screenshot.unlink()
        sys.exit(1)

    # Annotate with metadata
    result["label"]      = args.label
    result["model"]      = args.model
    result["screenshot"] = str(screenshot_path)
    result["scored_at"]  = datetime.utcnow().isoformat() + "Z"

    if tmp_screenshot and tmp_screenshot.exists():
        tmp_screenshot.unlink()

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.out:
        Path(args.out).write_text(output)
        print(f"[score] Saved to {args.out}", file=sys.stderr)

    print(output)


if __name__ == "__main__":
    main()
