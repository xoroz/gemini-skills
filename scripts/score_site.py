#!/usr/bin/env python3
"""score_site.py — Visual UX scorer for landing pages.

Takes a screenshot (or renders a local HTML / live URL) and scores it using
Claude vision API. Detects visual errors such as hero text overlap, broken
layouts, and unreadable content. Outputs structured JSON.

Usage:
  uv run scripts/score_site.py --screenshot path/to/shot.png [--out score.json]
  uv run scripts/score_site.py --html path/to/index.html [--out score.json]
  uv run scripts/score_site.py --url https://example.com [--out score.json]

Requires: ANTHROPIC_API_KEY in environment or .env
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load .env if present so the script works standalone (outside FastAPI)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ---------------------------------------------------------------------------
# Scoring prompt
# ---------------------------------------------------------------------------
SCORE_PROMPT = """You are a professional UX auditor reviewing a website screenshot.

Score this landing page on each category from 0 to 10 (10 = perfect, 0 = completely broken).
Be strict and realistic — a mediocre page should score 4-6, not 8-9.

SCORING CATEGORIES:
- hero: Hero section — background image visible, text readable, dark overlay working correctly, no raw HTML text printed directly on image without legible overlay
- navigation: Nav bar — logo present, links visible, CTA button present, looks structured and aligned
- typography: Font quality, clear visual hierarchy (H1 > H2 > body), readability
- color_contrast: Palette consistency, text vs background contrast (WCAG AA: 4.5:1 for normal text)
- layout: Section structure, proper spacing, no overflow or clipping, grids/flexbox working
- content: Content fills sections, no lorem ipsum, no visible placeholder gaps or empty blocks
- mobile_readiness: Hamburger icon visible in nav, responsive layout indicators present
- overall: Overall visual polish and professional appearance

VISUAL ERRORS — check for each and include the key in visual_errors array only if clearly present:
- "hero_text_overlap": HTML heading/subtitle text rendered directly on the hero image without a readable dark/color overlay, causing unreadable text or visual collision with the background image
- "broken_layout": One or more sections appear visually broken — elements overflowing their containers, mis-positioned, or clipped
- "missing_content": Visible empty sections, lorem ipsum placeholder text, or blank content blocks
- "unreadable_text": Text color is too close to background color, making content hard to read
- "nav_broken": Navigation bar appears broken — links overflowing, hamburger glitching, or structure collapsed
- "image_missing": Visible broken image placeholders (missing image icons shown by browser)
- "style_not_loaded": Page appears unstyled or CSS failed to load (plain HTML rendering)

Return ONLY this JSON with no commentary, no markdown fences:
{
  "scores": {
    "hero": <0-10>,
    "navigation": <0-10>,
    "typography": <0-10>,
    "color_contrast": <0-10>,
    "layout": <0-10>,
    "content": <0-10>,
    "mobile_readiness": <0-10>,
    "overall": <0-10>
  },
  "visual_errors": ["hero_text_overlap"],
  "issues": ["specific issue description"],
  "strengths": ["specific strength description"],
  "total": <sum of all 8 scores, 0-80>
}"""


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def take_screenshot(html_path: Path, output_path: Path) -> None:
    """Render a local HTML file to a PNG screenshot using Playwright."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output_path))
        browser.close()


def take_url_screenshot(url: str, output_path: Path) -> None:
    """Take a screenshot of a live URL using Playwright."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(output_path))
        browser.close()


# ---------------------------------------------------------------------------
# Scoring via Claude vision
# ---------------------------------------------------------------------------

def score_screenshot(screenshot_path: Path) -> dict:
    """Send a screenshot to Claude vision and return a UX score dict."""
    import anthropic

    suffix = screenshot_path.suffix.lower()
    media_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")

    with open(screenshot_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": SCORE_PROMPT},
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip accidental markdown fences
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].strip()

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Score a site screenshot with Claude vision")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--screenshot", help="Path to an existing screenshot file (PNG/WebP/JPG)")
    group.add_argument("--html", help="Path to index.html — will be rendered to a screenshot first")
    group.add_argument("--url", help="Live URL — will be screenshotted first")
    parser.add_argument("--out", help="Write JSON result to this path (also prints to stdout)")
    parser.add_argument("--label", default="site", help="Label for this score entry, e.g. 'original' or 'generated'")
    args = parser.parse_args()

    tmp_screenshot: Optional[Path] = None

    if args.screenshot:
        screenshot_path = Path(args.screenshot)
    elif args.html:
        html_path = Path(args.html)
        tmp_screenshot = html_path.parent / "_score_tmp.png"
        print(f"[score] Rendering {html_path} ...", file=sys.stderr)
        take_screenshot(html_path, tmp_screenshot)
        screenshot_path = tmp_screenshot
    else:
        tmp_screenshot = Path("/tmp/_score_url.png")
        print(f"[score] Screenshotting {args.url} ...", file=sys.stderr)
        take_url_screenshot(args.url, tmp_screenshot)
        screenshot_path = tmp_screenshot

    if not screenshot_path.exists():
        print(f"[score] ERROR: Screenshot not found at {screenshot_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[score] Scoring {screenshot_path} with Claude vision ...", file=sys.stderr)
    result = score_screenshot(screenshot_path)

    result["label"] = args.label
    result["screenshot"] = str(screenshot_path)
    result["scored_at"] = datetime.utcnow().isoformat() + "Z"

    # Clean up temporary screenshot
    if tmp_screenshot and tmp_screenshot.exists():
        tmp_screenshot.unlink()

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.out:
        Path(args.out).write_text(output)
        print(f"[score] Score saved to {args.out}", file=sys.stderr)

    print(output)


if __name__ == "__main__":
    main()
