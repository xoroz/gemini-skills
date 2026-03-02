#!/usr/bin/env python3
"""
tests/test-all.py — Full end-to-end integration test for Review Site Factory.

Steps:
  1. Server health check
  2. Scrape Google Maps → extract first result
  3. POST /generate-site with that data (MODE=DEV → cheap images)
  4. Tail build.log live until build completes  [LOCAL only]
  5. Validate output: index.html exists, style.css exists, all 6 images present  [LOCAL only]
  6. Open index.html with Playwright, take a screenshot, check DOM structure  [LOCAL only]

Environment overrides:
  QUERY            — Maps search query (default: parrucchiere la spezia)
  BASE_URL         — FastAPI base URL (default: http://localhost:8000)
  REMOTE_SITE_URL  — Web server base where sites are served (default: derived from host)
                     e.g. http://192.168.0.114  (nginx on port 80 serving /<slug>/index.html)
  WEBHOOK_URL      — Webhook for /generate-site (default: dummy)
  BUILD_WAIT       — Max seconds to wait for build (default: 900)
  SITES_DIR        — Where sites/ folder lives (default: auto-detected from script location)
  REMOTE           — Set to "true" / "1" / "yes" to skip local-only steps (default: false)

CLI args (override env vars):
  --remote                  Enable remote mode (skips local filesystem checks)
  --host HOST               Remote host IP / hostname
  --port PORT               FastAPI port (default: 8000)
  --base-url URL            Full FastAPI base URL (overrides --host / --port)
  --remote-url URL          Web server base URL where sites are served
                            (default: http://<host>  i.e. port 80, path /<slug>/index.html)
  --business-type TYPE      Business type for Maps search  (e.g. "parrucchiere")
  --location LOC            Location for Maps search        (e.g. "la spezia")
  --query QUERY             Raw Maps search query (overridden by --business-type + --location)
  --build-wait SECONDS      Max seconds to wait for build (remote: polls site URL)
  --webhook-url URL         Webhook URL passed to /generate-site

Usage examples:
  # Local (default):
  python tests/test-all.py

  # Remote — API on :8080, sites served by nginx on :80
  python tests/test-all.py --remote --host 192.168.0.114 --port 8080
  # ↑ REMOTE_SITE_URL will default to http://192.168.0.114
  # Site will be validated at http://192.168.0.114/<slug>/index.html

  # Remote with explicit site URL root:
  python tests/test-all.py --remote --host 192.168.0.114 --port 8080 \
      --remote-url http://192.168.0.114/sites

  # Remote via env:
  REMOTE=true BASE_URL=http://192.168.0.114:8080 \
    REMOTE_SITE_URL=http://192.168.0.114 python tests/test-all.py
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import httpx
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env if present (optional — system env vars always take precedence)
# ---------------------------------------------------------------------------
_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
_env_loaded = False
if os.path.exists(_env_path):
    _env_loaded = True
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                # Override locally empty shell variables with real file values
                if not os.environ.get(_k):
                    os.environ[_k] = _v

# ─── CLI args ─────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review Site Factory — full integration test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--remote", action="store_true", default=None,
        help="Remote mode: skip local filesystem steps (build.log, file validation, Playwright file://)",
    )
    parser.add_argument("--host",       metavar="HOST",   help="Remote host IP or hostname")
    parser.add_argument("--port",       metavar="PORT",   help="FastAPI port (default: 8000)")
    parser.add_argument("--base-url",   metavar="URL",    help="Full FastAPI base URL (overrides --host/--port)")
    parser.add_argument("--remote-url", metavar="URL",
        help="Web server base URL where sites are served "
             "(default: http://<host>  →  http://<host>/<slug>/index.html)")
    # Search — can use structured args OR a raw query string
    parser.add_argument("--business-type", metavar="TYPE",
        help="Business type for Maps search  (e.g. \"parrucchiere\")")
    parser.add_argument("--location",      metavar="LOC",
        help="Location for Maps search  (e.g. \"la spezia\")")
    parser.add_argument("--query",         metavar="QUERY",
        help="Raw Maps search query (overridden by --business-type + --location)")
    parser.add_argument("--build-wait", metavar="SECONDS",type=int, help="Max build wait in seconds")
    parser.add_argument("--webhook-url",metavar="URL",    help="Webhook URL for /generate-site")
    return parser.parse_args()


ARGS = _parse_args()

# ─── Config (args take precedence over env, env over defaults) ────────────────
def _resolve_bool(args_val, env_key: str, default: bool) -> bool:
    if args_val is not None:
        return bool(args_val)
    env = os.environ.get(env_key, "").lower()
    if env in ("true", "1", "yes"):
        return True
    if env in ("false", "0", "no"):
        return False
    return default

REMOTE = _resolve_bool(ARGS.remote, "REMOTE", False)

def _resolve_base_url() -> str:
    # 1. explicit --base-url
    if ARGS.base_url:
        return ARGS.base_url.rstrip("/")
    # 2. BASE_URL env
    if os.environ.get("BASE_URL"):
        return os.environ["BASE_URL"].rstrip("/")
    # 3. --host / --port combo
    if ARGS.host:
        port = ARGS.port or os.environ.get("PORT", "8000")
        return f"http://{ARGS.host}:{port}"
    # 4. PORT env
    port = os.environ.get("PORT", "8000")
    return f"http://localhost:{port}"

BASE_URL    = _resolve_base_url()
WEBHOOK_URL = ARGS.webhook_url or os.environ.get("WEBHOOK_URL", "https://webhook.site/dummy-test-url")
BUILD_WAIT  = ARGS.build_wait  or int(os.environ.get("BUILD_WAIT", "900"))

# Search query resolution:
#   --business-type + --location  → structured (preferred)
#   --query / QUERY env           → raw fallback
#   default                       → "parrucchiere la spezia"
BUSINESS_TYPE: str = (ARGS.business_type or "").strip()
LOCATION:      str = (ARGS.location      or "").strip()
if BUSINESS_TYPE and LOCATION:
    QUERY = f"{BUSINESS_TYPE} {LOCATION}"          # display / slug purposes
else:
    QUERY = ARGS.query or os.environ.get("QUERY", "parrucchiere la spezia")
    BUSINESS_TYPE = ""
    LOCATION      = ""

API_TOKEN = os.environ.get("API_TOKEN", "")
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
SITE_LANG = os.environ.get("SITE_LANG", "it")

def _resolve_remote_site_url() -> str:
    """
    The web server URL root where generated sites are accessible.
    Separate from BASE_URL (FastAPI) because nginx/apache may serve on a
    different port (usually 80) or path prefix.

    Priority:
      1. --remote-url CLI arg
      2. REMOTE_SITE_URL env var
      3. Derive from --host  →  http://<host>   (port 80, no path)
      4. Derive from BASE_URL host, stripping the port  →  http://<host>
    """
    if ARGS.remote_url:
        return ARGS.remote_url.rstrip("/")
    if os.environ.get("REMOTE_SITE_URL"):
        return os.environ["REMOTE_SITE_URL"].rstrip("/")
    # Derive from explicit --host
    if ARGS.host:
        return f"http://{ARGS.host}"
    # Derive from BASE_URL by stripping any non-80 port
    import urllib.parse as _up
    parsed = urllib.parse.urlparse(BASE_URL)
    return f"{parsed.scheme}://{parsed.hostname}"

REMOTE_SITE_URL = _resolve_remote_site_url()

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
SKIP_COUNT = 0


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


def skip(msg: str):
    global SKIP_COUNT
    SKIP_COUNT += 1
    print(f"  {YELLOW}⏭ SKIP{NC}: {msg}")


def info(msg: str):
    print(f"  {CYAN}ℹ{NC}  {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{NC}  {msg}")


def summary():
    sep()
    print()
    status = (
        f"{GREEN}{PASS_COUNT} passed{NC}  |  "
        f"{RED}{FAIL_COUNT} failed{NC}  |  "
        f"{YELLOW}{SKIP_COUNT} skipped{NC}"
    )
    print(f"  {BOLD}Results: {status}{NC}")
    print()


def slug(name: str) -> str:
    """Mirror create.sh slug logic: lowercase, spaces→hyphens, strip non-alnum-hyphen."""
    s = name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


# ─── Step 1: Health check ─────────────────────────────────────────────────────
def step_health():
    print(f"\n{YELLOW}[Step 1] Server health check{NC}")
    try:
        r = httpx.get(f"{BASE_URL}/docs", timeout=5)
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
    print(f"\n{YELLOW}[Step 2] Scrape Google Maps{NC}")

    # Build request: prefer structured business_type + location params
    if BUSINESS_TYPE and LOCATION:
        params = {
            "business_type": BUSINESS_TYPE,
            "location":      LOCATION,
            "max_results":   1,
        }
        info(f'business_type: "{BUSINESS_TYPE}"')
        info(f'location     : "{LOCATION}"')
        # Show the Maps URL that will be constructed server-side
        combined = urllib.parse.quote_plus(f"{BUSINESS_TYPE} {LOCATION}")
        info(f'Maps URL     : https://www.google.com/maps/search/{combined}?hl={SITE_LANG}')
    else:
        params = {
            "query":       QUERY,
            "max_results": 1,
        }
        encoded = urllib.parse.quote_plus(QUERY)
        info(f'query: "{QUERY}"')
        info(f'Maps URL: https://www.google.com/maps/search/{encoded}?hl={SITE_LANG}')

    info("\u23f3 May take up to 30 seconds...")
    print()

    try:
        r = httpx.get(f"{BASE_URL}/scrape-maps", params=params, headers=AUTH_HEADERS, timeout=130)
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


# ─── Step 2.5: Quantity cap & cache invalidation tests ──────────────────────────
def step_scrape_cache_and_qty():
    """
    Regression tests for two bugs fixed in main.py:
      Bug 1 — max_results not respected (API returned more than requested)
      Bug 2 — cache ignores quantity (stale cache served fewer/wrong results)

    Strategy
    --------
    Pass A  max_results=2  → populates cache, asserts ≤2 results returned
    Pass B  max_results=2  → should be instant cache hit, still ≤2 results
    Pass C  max_results=3  → cache entry for N=2 must NOT be returned;
                             a fresh scrape fires and returns ≤3 results
    """
    print(f"\n{YELLOW}[Step 2.5] Quantity cap & cache invalidation regression tests{NC}")

    # Build params — reuse the configured query so we don't trigger a 3rd Maps search topic
    if BUSINESS_TYPE and LOCATION:
        base_params: dict = {"business_type": BUSINESS_TYPE, "location": LOCATION}
    else:
        base_params = {"query": QUERY}

    def _scrape(n: int, label: str) -> tuple[list, float]:
        params = {**base_params, "max_results": n}
        t0 = time.monotonic()
        try:
            r = httpx.get(
                f"{BASE_URL}/scrape-maps",
                params=params,
                headers=AUTH_HEADERS,
                timeout=140,
            )
            elapsed = time.monotonic() - t0
            if r.status_code != 200:
                fail(f"{label}: HTTP {r.status_code}", fatal=False)
                return [], elapsed
            return r.json().get("data", []), elapsed
        except Exception as exc:
            fail(f"{label}: request error — {exc}", fatal=False)
            return [], time.monotonic() - t0

    # ── Pass A: first call seeds the cache ──────────────────────────────────────
    info("Pass A — max_results=2 (seeds cache)")
    items_a, dur_a = _scrape(2, "Pass A")
    info(f"  Got {len(items_a)} result(s) in {dur_a:.1f}s")
    if len(items_a) <= 2:
        ok(f"Pass A: quantity cap respected ({len(items_a)} ≤ 2)")
    else:
        fail(f"Pass A: got {len(items_a)} results — expected ≤2 (quantity cap bug!)")

    # ── Pass B: same query + same N → should hit cache and return instantly ──────
    info("Pass B — max_results=2 (should be cache hit)")
    items_b, dur_b = _scrape(2, "Pass B")
    info(f"  Got {len(items_b)} result(s) in {dur_b:.1f}s")
    if len(items_b) <= 2:
        ok(f"Pass B: quantity cap respected ({len(items_b)} ≤ 2)")
    else:
        fail(f"Pass B: got {len(items_b)} results — expected ≤2 (quantity cap bug!)")
    # Cache hit is typically <1 s; scrape takes 10-120 s. A 5-second ceiling is generous.
    CACHE_HIT_THRESHOLD = 5.0
    if dur_b < CACHE_HIT_THRESHOLD:
        ok(f"Pass B: cache hit confirmed ({dur_b:.1f}s < {CACHE_HIT_THRESHOLD}s threshold)")
    else:
        warn(f"Pass B: took {dur_b:.1f}s — slower than expected for a cache hit. "
             "Network latency or server load may explain this.")

    # ── Pass C: larger quantity → cache for N=2 must NOT be served ──────────────
    info("Pass C — max_results=3 (must bypass N=2 cache and scrape fresh)")
    items_c, dur_c = _scrape(3, "Pass C")
    info(f"  Got {len(items_c)} result(s) in {dur_c:.1f}s")
    if len(items_c) <= 3:
        ok(f"Pass C: quantity cap respected ({len(items_c)} ≤ 3)")
    else:
        fail(f"Pass C: got {len(items_c)} results — expected ≤3 (quantity cap bug!)")
    # If the N=2 cache was incorrectly served, we'd get ≤2 items instantly.
    # A fresh scrape always takes > CACHE_HIT_THRESHOLD seconds.
    if dur_c >= CACHE_HIT_THRESHOLD:
        ok(f"Pass C: fresh scrape triggered as expected ({dur_c:.1f}s ≥ {CACHE_HIT_THRESHOLD}s)")
    else:
        # Either the server was very fast OR the old (wrong) cache was returned
        if len(items_c) <= 2 and len(items_a) >= 2:
            fail(
                f"Pass C: got {len(items_c)} items in {dur_c:.1f}s — "
                "looks like the N=2 cache was served instead of a fresh scrape! "
                "(cache-bypass bug may still be present)"
            )
        else:
            warn(
                f"Pass C: completed in {dur_c:.1f}s (faster than threshold). "
                "Could be a very fast network or a warm Maps response."
            )


# ─── Step 3: Trigger build ────────────────────────────────────────────────────
def step_generate(biz: dict) -> str:
    """Returns the slug (business name slugified) used as site identifier."""
    name = biz["business_name"]
    print(f"\n{YELLOW}[Step 3] Trigger site build for \"{name}\"{NC}")
    mode_val = os.environ.get("MODE", "DEV")
    info(f"MODE={mode_val}")
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
        r = httpx.post(f"{BASE_URL}/generate-site",
                          json=payload, headers=AUTH_HEADERS, timeout=10)
        resp = r.json()
    except Exception as e:
        fail(f"/generate-site request failed: {e}", fatal=True)
        return ""

    print("  Response:")
    print("  " + json.dumps(resp, indent=2).replace("\n", "\n  "))
    print()

    if resp.get("status") == "processing":
        ok("/generate-site accepted the job (status=processing)")
    else:
        fail(f"/generate-site unexpected status: {resp.get('status')}", fatal=True)

    site_slug = slug(name)
    if REMOTE:
        info(f"Remote mode — site slug: {site_slug}")
    else:
        site_dir = SITES_DIR / site_slug
        info(f"Expected output: {site_dir}")

    return site_slug


# ─── Step 4: Wait for build via API ───────────────────────────────────────────
def step_wait_api(site_slug: str):
    """
    Wait for build by polling the /status/{job_id} endpoint.
    Works for both local and remote modes.
    """
    print(f"\n{YELLOW}[Step 4] Waiting for build to complete (polling API){NC}")
    info(f"Polling : {BASE_URL}/status/{site_slug}")
    info(f"Timeout : {BUILD_WAIT}s  (set BUILD_WAIT env to change)")
    print()

    deadline = time.time() + BUILD_WAIT
    poll_interval = 5

    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/status/{site_slug}", headers=AUTH_HEADERS, timeout=5)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status")
                if status == "complete":
                    ok(f"Build completed! Site is ready.")
                    return SITES_DIR / site_slug
                elif status == "failed":
                    fail("Build failed according to API!", fatal=True)
                else:
                    print(f"  {DIM}Status: {status} — still building...{NC}")
            else:
                warn(f"API returned {r.status_code} — continuing to poll")
        except Exception as e:
            warn(f"Error calling status API: {e} — continuing to poll")

        time.sleep(poll_interval)

    fail(f"Build did not complete within {BUILD_WAIT}s", fatal=True)


# ─── Step 4.5: Fetch build log & stats ───────────────────────────────────────
def _parse_build_stats(log_text: str) -> dict:
    """Parse key metrics out of a raw build.log string."""
    import re as _re
    stats: dict = {}

    m = _re.search(r"Total time:\s+([\d]+m\s+[\d]+s)", log_text)
    if m: stats["total_time"] = m.group(1).strip()

    m = _re.search(r"Mode:\s+(\w+)\s+\(([^)]+)\)", log_text)
    if m: stats["mode"] = f"{m.group(1)} ({m.group(2).strip()})"

    m = _re.search(r"Generated:\s+(\d+)\s*/\s*(\d+)", log_text)
    if m:
        stats["images_generated"] = int(m.group(1))
        stats["images_total"]     = int(m.group(2))

    m = _re.search(r"Failed:\s+(\d+)", log_text)
    if m: stats["images_failed"] = int(m.group(1))

    m = _re.search(r"Total:\s+~?\$?([\d.]+)", log_text)
    if m: stats["estimated_cost_usd"] = float(m.group(1))

    m = _re.search(r"Assets size:\s+(\S+)", log_text)
    if m: stats["assets_size"] = m.group(1).strip()

    m = _re.search(r"Total size:\s+(\S+)", log_text)
    if m: stats["total_size"] = m.group(1).strip()

    # 🌐 URL=http://...  line written by create.sh
    m = _re.search(r"URL=(https?://\S+)", log_text)
    if m: stats["site_url"] = m.group(1).strip()

    return stats


def step_build_log(site_slug: str):
    """
    Fetch and parse build.log.

    Remote: nginx serves it statically at REMOTE_SITE_URL/<slug>/build.log
    Local : read directly from SITES_DIR/<slug>/build.log
    """
    print(f"\n{YELLOW}[Step 4.5] Build log & stats{NC}")

    log_text: str = ""

    if REMOTE:
        log_url = f"{REMOTE_SITE_URL}/{site_slug}/build.log"
        info(f"Fetching: {log_url}")
        try:
            r = httpx.get(log_url, timeout=10)
            if r.status_code == 200:
                log_text = r.text
                ok(f"build.log fetched ({len(log_text):,} bytes)")
            else:
                warn(f"build.log returned HTTP {r.status_code}")
                skip("Build log (not available yet)")
                return
        except Exception as e:
            warn(f"Could not fetch build.log: {e}")
            skip("Build log (fetch error)")
            return
    else:
        log_path = SITES_DIR / site_slug / "build.log"
        info(f"Reading: {log_path}")
        if not log_path.exists():
            warn("build.log not found on disk")
            skip("Build log (file missing)")
            return
        log_text = log_path.read_text(errors="replace")
        ok(f"build.log read ({len(log_text):,} bytes)")

    # Detect build state from tail of log
    tail = log_text[-2000:]
    if "🌐 URL=" in tail:
        build_status, sc = "COMPLETE", GREEN
    elif "❌ Failed" in tail or "exit 1" in tail:
        build_status, sc = "FAILED",   RED
    else:
        build_status, sc = "IN PROGRESS", YELLOW

    print()
    print(f"  {BOLD}Build status:{NC} {sc}{build_status}{NC}")
    print()

    stats = _parse_build_stats(log_text)
    if stats:
        print(f"  {CYAN}{'─'*50}{NC}")
        print(f"  {BOLD}  📊 Build Stats{NC}")
        print(f"  {CYAN}{'─'*50}{NC}")
        if "total_time"         in stats: print(f"    ⏱️  Time       : {stats['total_time']}")
        if "mode"               in stats: print(f"    🏗️  Mode       : {stats['mode']}")
        if "images_generated"   in stats:
            imgs_ok   = stats.get("images_generated", 0)
            imgs_tot  = stats.get("images_total", 0)
            imgs_fail = stats.get("images_failed", 0)
            print(f"    🖼️  Images     : {imgs_ok}/{imgs_tot} generated"
                  + (f"  {RED}({imgs_fail} failed){NC}" if imgs_fail else f"  {GREEN}✓{NC}"))
        if "assets_size"        in stats: print(f"    📦 Assets     : {stats['assets_size']}")
        if "total_size"         in stats: print(f"    📁 Total size : {stats['total_size']}")
        if "estimated_cost_usd" in stats: print(f"    💰 Est. cost  : ${stats['estimated_cost_usd']:.3f}")
        if "site_url"           in stats: print(f"    🌐 Live URL   : {BOLD}{stats['site_url']}{NC}")
        print(f"  {CYAN}{'─'*50}{NC}")
        print()
        ok("Build stats parsed successfully")
    else:
        warn("Could not parse stats from log (build may still be in progress)")
        skip("Stats parse")




def step_validate_local(site_dir: Path):
    print(f"\n{YELLOW}[Step 5] Validate output & open with Playwright (LOCAL){NC}")

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

    # Playwright validation (local file://)
    print("  Playwright checks:")
    _playwright_validate_local(site_dir)


def _playwright_validate_local(site_dir: Path):
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

        _playwright_dom_checks(page, screenshot)
        browser.close()


# ─── Step 5b: REMOTE — Validate via HTTP + Playwright (http://) ───────────────
def step_validate_remote(site_slug: str):
    print(f"\n{YELLOW}[Step 5] Validate output (REMOTE — HTTP checks){NC}")
    info("Local file checks are SKIPPED in remote mode.")
    skip("Local file existence checks (not accessible from this machine)")
    skip("Local build.log tailing (not accessible from this machine)")

    # Primary URL: REMOTE_SITE_URL/<slug>/index.html
    # e.g. http://192.168.0.114/parrucchiere-la-spezia/index.html
    primary_url = f"{REMOTE_SITE_URL}/{site_slug}/index.html"

    # Fallback candidates if primary doesn't respond with 200
    fallback_candidates = [
        f"{REMOTE_SITE_URL}/{site_slug}/",
        f"{REMOTE_SITE_URL}/sites/{site_slug}/index.html",
        f"{REMOTE_SITE_URL}/sites/{site_slug}/",
    ]

    site_url = None
    print()
    info(f"Primary site URL : {primary_url}")
    info(f"(override with --remote-url or REMOTE_SITE_URL env)")
    print()

    # Try primary first
    try:
        r = httpx.get(primary_url, timeout=8)
        if r.status_code == 200:
            site_url = primary_url
            ok(f"Site reachable at {primary_url}")
        else:
            warn(f"Primary URL returned HTTP {r.status_code} — trying fallbacks...")
    except Exception as e:
        warn(f"Primary URL error: {e} — trying fallbacks...")

    # Fallbacks
    if not site_url:
        for url in fallback_candidates:
            try:
                r = httpx.get(url, timeout=5)
                if r.status_code == 200 and "html" in r.headers.get("content-type", "").lower():
                    site_url = url
                    ok(f"Site reachable (fallback) at {url}")
                    break
                else:
                    info(f"  {url} → HTTP {r.status_code}")
            except Exception as e:
                info(f"  {url} → error: {e}")

    if site_url:
        print()
        print("  Playwright checks (HTTP remote):")
        _playwright_validate_remote(site_url, site_slug)
    else:
        fail(f"Could not reach site at {primary_url} or any fallback.")
        warn(f"Tip: use --remote-url to set the correct web server base URL")
        warn(f"     e.g.  --remote-url http://192.168.0.114")
        skip("Playwright remote check (no reachable URL found)")


def _playwright_validate_remote(site_url: str, site_slug: str):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("playwright not installed — skipping browser validation")
        warn("Install: pip install playwright && playwright install chromium")
        return

    screenshot_path = TESTS_DIR / f"remote-screenshot-{site_slug}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            page.goto(site_url, wait_until="networkidle", timeout=20000)
        except PWTimeout:
            warn("Page load timed out — taking screenshot anyway")
        except Exception as e:
            fail(f"Playwright could not open remote page: {e}")
            browser.close()
            return

        _playwright_dom_checks(page, screenshot_path)
        browser.close()


def _playwright_dom_checks(page, screenshot: Path):
    """Shared DOM checks for both local and remote Playwright validation."""
    page.screenshot(path=str(screenshot), full_page=True)
    ok(f"Screenshot saved → {screenshot}")

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

    nav = page.locator("nav, header").count()
    if nav > 0:
        ok("Navigation/header element found")
    else:
        warn("No <nav> or <header> found — may be styled differently")

    body_text = page.locator("body").inner_text().lower()
    if any(kw in body_text for kw in ["contatt", "contact", "telefon", "phone"]):
        ok("Contact information section detected")
    else:
        warn("No contact keywords found in body text")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print()
    print(f"{BOLD}{CYAN}🧪 Review Site Factory — Full Integration Test{NC}")
    if _env_loaded:
        token_str = f"{API_TOKEN[:4]}...{API_TOKEN[-4:]}" if len(API_TOKEN) > 8 else "NOT SET/EMPTY"
        print(f"   .env    : Loaded (API_TOKEN={token_str})")
    print(f"   API     : {BASE_URL}")
    print(f"   Query   : {QUERY}")
    mode_val = os.environ.get("MODE", "DEV")
    print(f"   Mode    : {mode_val}")
    if REMOTE:
        print(f"   Remote  : {BOLD}{YELLOW}ON{NC} — local filesystem steps will be SKIPPED")
        print(f"   Site URL: {REMOTE_SITE_URL}/<slug>/index.html")
    else:
        print(f"   Remote  : OFF — running full local test")
        print(f"   Sites   : {SITES_DIR}")
    sep()

    # Step 1: Health (always runs)
    step_health()
    sep()

    # Step 2: Scrape (always runs — it's just an API call)
    biz = step_scrape()
    sep()

    # Step 2.5: Quantity cap & cache invalidation regression tests
    step_scrape_cache_and_qty()
    sep()

    # Step 3: Trigger build (always runs — it's just an API call)
    site_slug = step_generate(biz)
    sep()

    # Step 4: Wait for build
    site_dir = step_wait_api(site_slug)
    sep()

    # Step 4.5: Fetch build log & stats from API (both modes)
    step_build_log(site_slug)
    sep()

    # Step 5: Validate
    if REMOTE:
        step_validate_remote(site_slug)
    else:
        step_validate_local(site_dir)
    sep()

    summary()

    if FAIL_COUNT > 0:
        sys.exit(1)

    print(f"  {GREEN}✅ All checks passed!{NC}")
    if not REMOTE:
        site_dir = SITES_DIR / site_slug
        print(f"  Open the site: {BOLD}file://{(site_dir / 'index.html').resolve()}{NC}")
    else:
        print(f"  API server   : {BOLD}{BASE_URL}{NC}")
        print(f"  Live site    : {BOLD}{REMOTE_SITE_URL}/{site_slug}/index.html{NC}")
    print()


if __name__ == "__main__":
    main()
