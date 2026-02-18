#!/usr/bin/env python3
"""
tests/test-all.py — Full end-to-end integration test for Review Site Factory.

Steps:
  1. Server health check
  2. Scrape Google Maps → extract first result
  3. POST /generate-site with that data (MODE=DEV → cheap images)
  4. Tail build.log live until build completes (or times out)
  5. Validate output: index.html exists, style.css exists, all 6 images present
  6. Open index.html with Playwright, take a screenshot, check DOM structure

Environment overrides:
  QUERY       — Maps search query (default: parrucchiere la spezia)
  BASE_URL    — API base URL (default: http://localhost:8000)
  WEBHOOK_URL — Webhook for /generate-site (default: dummy)
  BUILD_WAIT  — Max seconds to wait for build (default: 900)
  SITES_DIR   — Where sites/ folder lives (default: auto-detected from script location)
"""

import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

# ─── Config ───────────────────────────────────────────────────────────────────
BASE_URL    = os.environ.get("BASE_URL",    "http://localhost:8000")
QUERY       = os.environ.get("QUERY",       "parrucchiere la spezia")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://webhook.site/dummy-test-url")
BUILD_WAIT  = int(os.environ.get("BUILD_WAIT", "900"))   # seconds

# Resolve project root (tests/ lives one level below root)
TESTS_DIR  = Path(__file__).parent.resolve()
PROJECT    = TESTS_DIR.parent
SITES_DIR  = Path(os.environ.get("SITES_DIR", str(PROJECT / "sites")))

# ─── Colours ──────────────────────────────────────────────────────────────────
GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
NC     = "\033[0m"

PASS_COUNT = 0
FAIL_COUNT = 0


def sep():
    print(f"{CYAN}──────────────────────────────────────────────────────{NC}")


def ok(msg: str):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  {GREEN}✅ PASS{NC}: {msg}")


def fail(msg: str, fatal: bool = False):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  {RED}❌ FAIL{NC}: {msg}")
    if fatal:
        summary()
        sys.exit(1)


def info(msg: str):
    print(f"  {CYAN}ℹ{NC}  {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{NC}  {msg}")


def summary():
    sep()
    print()
    status = f"{GREEN}{PASS_COUNT} passed{NC}  |  {RED}{FAIL_COUNT} failed{NC}"
    print(f"  {BOLD}Results: {status}{NC}")
    print()


def slug(name: str) -> str:
    """Mirror create.sh slug logic: lowercase, spaces→hyphens, strip non-alnum-hyphen."""
    s = name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


# ─── Step 1: Health check ─────────────────────────────────────────────────────
def step_health():
    print(f"\n{YELLOW}[Step 1/5] Server health check{NC}")
    try:
        r = requests.get(f"{BASE_URL}/docs", timeout=5)
        if r.status_code == 200:
            ok(f"Server reachable at {BASE_URL}")
        else:
            fail(f"Server returned HTTP {r.status_code}", fatal=True)
    except Exception as e:
        fail(f"Cannot reach server: {e}", fatal=True)
        print()
        print("  Start it with:")
        print("    source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000")


# ─── Step 2: Scrape ───────────────────────────────────────────────────────────
def step_scrape() -> dict:
    print(f"\n{YELLOW}[Step 2/5] Scrape Google Maps{NC}")
    info(f'Query: "{QUERY}" (max_results=1)')
    info("⏳ May take up to 30 seconds...")
    print()

    encoded = urllib.parse.quote_plus(QUERY)
    try:
        r = requests.get(f"{BASE_URL}/scrape-maps?query={encoded}&max_results=1", timeout=130)
        data = r.json()
    except Exception as e:
        fail(f"Scrape request failed: {e}", fatal=True)
        return {}

    print("  Response:")
    print("  " + json.dumps(data, indent=2, ensure_ascii=False).replace("\n", "\n  "))
    print()

    if data.get("status") != "success" or not data.get("data"):
        fail("Scrape returned no results", fatal=True)
        return {}

    biz = data["data"][0]
    if not biz.get("business_name"):
        fail("Scrape result has no business_name", fatal=True)
        return {}

    ok(f"Scraped: \"{biz['business_name']}\"")
    info(f"  niche:   {biz.get('niche', '—')}")
    info(f"  address: {biz.get('address', '—')}")
    info(f"  tel:     {biz.get('tel', '—')}")
    return biz


# ─── Step 3: Trigger build ────────────────────────────────────────────────────
def step_generate(biz: dict) -> Path:
    name = biz["business_name"]
    print(f"\n{YELLOW}[Step 3/5] Trigger site build for \"{name}\"{NC}")
    info("MODE=DEV → using sourceful/riverflow-v2-fast (cheap/fast images)")
    info("API returns immediately; build runs in background.")
    print()

    payload = {
        "business_name": name,
        "niche":         biz.get("niche", ""),
        "address":       biz.get("address", ""),
        "tel":           biz.get("tel", ""),
        "webhook_url":   WEBHOOK_URL,
    }
    print("  Payload:")
    print("  " + json.dumps(payload, indent=2, ensure_ascii=False).replace("\n", "\n  "))
    print()

    try:
        r = requests.post(f"{BASE_URL}/generate-site",
                          json=payload, timeout=10)
        resp = r.json()
    except Exception as e:
        fail(f"/generate-site request failed: {e}", fatal=True)
        return Path()

    print("  Response:")
    print("  " + json.dumps(resp, indent=2).replace("\n", "\n  "))
    print()

    if resp.get("status") == "processing":
        ok("/generate-site accepted the job (status=processing)")
    else:
        fail(f"/generate-site unexpected status: {resp.get('status')}", fatal=True)

    site_slug = slug(name)
    site_dir  = SITES_DIR / site_slug
    info(f"Expected output: {site_dir}")
    return site_dir


# ─── Step 4: Tail build log ───────────────────────────────────────────────────
def step_wait(site_dir: Path):
    log_file = site_dir / "build.log"
    print(f"\n{YELLOW}[Step 4/5] Waiting for build to complete{NC}")
    info(f"Tailing: {log_file}")
    info(f"Timeout: {BUILD_WAIT}s  (set BUILD_WAIT env to change)")
    print()

    deadline = time.time() + BUILD_WAIT
    last_pos  = 0

    # Wait for log file to appear (create.sh creates the folder first)
    print(f"  {DIM}Waiting for build.log to appear...{NC}", end="", flush=True)
    while not log_file.exists():
        if time.time() > deadline:
            print()
            fail(f"build.log never appeared in {site_dir}", fatal=True)
        time.sleep(2)
        print(".", end="", flush=True)
    print(f"  {GREEN}found{NC}")
    print()

    # Tail the log until we see the final "Open:" line (unique — only at end of build)
    # The header also contains ═══ separators so we cannot use those.
    DONE_MARKER = "🌐 Open:"
    done = False

    while time.time() < deadline:
        with open(log_file, "r", errors="replace") as f:
            f.seek(last_pos)
            chunk = f.read()
            if chunk:
                # Print new lines with indentation
                for line in chunk.splitlines():
                    print(f"  {DIM}{line}{NC}")
                last_pos += len(chunk.encode("utf-8", errors="replace"))
                if DONE_MARKER in chunk:
                    done = True
                    break
        time.sleep(1)

    # Give the OS a moment to flush any final file writes
    time.sleep(1)
    print()
    if done:
        ok("Build completed (🌐 Open: marker detected in log)")
    else:
        fail(f"Build did not complete within {BUILD_WAIT}s", fatal=True)


# ─── Step 5: Validate output + Playwright ─────────────────────────────────────
def step_validate(site_dir: Path):
    print(f"\n{YELLOW}[Step 5/5] Validate output & open with Playwright{NC}")

    # File checks
    required_files = [
        site_dir / "index.html",
        site_dir / "style.css",
        site_dir / "assets" / "hero.png",
        site_dir / "assets" / "gallery-1.png",
        site_dir / "assets" / "gallery-2.png",
        site_dir / "assets" / "workshop.png",
        site_dir / "assets" / "detail.png",
        site_dir / "assets" / "process.png",
    ]

    print("  File checks:")
    all_files_ok = True
    for f in required_files:
        rel = f.relative_to(site_dir)
        if f.exists() and f.stat().st_size > 0:
            size = f.stat().st_size
            print(f"    {GREEN}✓{NC}  {rel}  {DIM}({size:,} bytes){NC}")
        else:
            print(f"    {RED}✗{NC}  {rel}  {RED}MISSING or EMPTY{NC}")
            all_files_ok = False

    if all_files_ok:
        ok("All required files present and non-empty")
    else:
        fail("Some required files are missing or empty")

    print()

    # Playwright validation
    print("  Playwright checks:")
    _playwright_validate(site_dir)


def _playwright_validate(site_dir: Path):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("playwright not installed — skipping browser validation")
        warn("Install: pip install playwright && playwright install chromium")
        return

    index_html = site_dir / "index.html"
    screenshot  = site_dir / "test-screenshot.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            page.goto(f"file://{index_html.resolve()}", wait_until="networkidle", timeout=15000)
        except PWTimeout:
            warn("Page load timed out — taking screenshot anyway")
        except Exception as e:
            fail(f"Playwright could not open page: {e}")
            browser.close()
            return

        # Screenshot
        page.screenshot(path=str(screenshot), full_page=True)
        ok(f"Screenshot saved → {screenshot.relative_to(site_dir.parent.parent)}")

        # DOM checks
        title = page.title()
        if title:
            ok(f"Page has <title>: \"{title}\"")
        else:
            fail("Page has no <title>")

        h1_count = page.locator("h1").count()
        if h1_count >= 1:
            h1_text = page.locator("h1").first.inner_text()
            ok(f"Found <h1>: \"{h1_text[:60]}\"")
        else:
            fail("No <h1> found on page")

        # Check images actually loaded (not broken)
        imgs = page.locator("img").all()
        broken = 0
        for img in imgs:
            natural_w = img.evaluate("el => el.naturalWidth")
            if natural_w == 0:
                broken += 1
        if broken == 0:
            ok(f"All {len(imgs)} images loaded successfully (naturalWidth > 0)")
        else:
            fail(f"{broken}/{len(imgs)} images are broken (naturalWidth=0)")

        # Check nav exists
        nav = page.locator("nav, header").count()
        if nav > 0:
            ok("Navigation/header element found")
        else:
            warn("No <nav> or <header> found — may be styled differently")

        # Check contact section
        body_text = page.locator("body").inner_text().lower()
        if any(kw in body_text for kw in ["contatt", "contact", "telefon", "phone"]):
            ok("Contact information section detected")
        else:
            warn("No contact keywords found in body text")

        browser.close()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print()
    print(f"{BOLD}{CYAN}🧪 Review Site Factory — Full Integration Test{NC}")
    print(f"   Server  : {BASE_URL}")
    print(f"   Query   : {QUERY}")
    print(f"   Mode    : DEV (forced — cheap images for testing)")
    print(f"   Sites   : {SITES_DIR}")
    sep()

    step_health()
    sep()

    biz = step_scrape()
    sep()

    site_dir = step_generate(biz)
    sep()

    step_wait(site_dir)
    sep()

    step_validate(site_dir)
    sep()

    summary()

    if FAIL_COUNT > 0:
        sys.exit(1)

    print(f"  {GREEN}✅ All checks passed!{NC}")
    print(f"  Open the site: {BOLD}file://{(site_dir / 'index.html').resolve()}{NC}")
    print()


if __name__ == "__main__":
    main()
