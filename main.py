from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
import re
import urllib.parse
import asyncio
import signal
import httpx
import os

# ---------------------------------------------------------------------------
# Load .env if present (optional — system env vars always take precedence)
# ---------------------------------------------------------------------------
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ---------------------------------------------------------------------------
# REMOTE_SITE_URL — the public web-server root where generated sites are served
# e.g. http://192.168.0.114   → sites live at http://192.168.0.114/<slug>/index.html
# Set in .env or as a system environment variable.
# ---------------------------------------------------------------------------
REMOTE_SITE_URL: str = os.environ.get("REMOTE_SITE_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# SITE_LANG — language for Google Maps search results (hl= param)
# Set in .env or as a system environment variable.
# Default: it (Italian)
# ---------------------------------------------------------------------------
SITE_LANG: str = os.environ.get("SITE_LANG", "it").strip().lower()

# =============================================================================
# ⏱️  TIMEOUTS  — edit these if builds are consistently faster/slower
# =============================================================================
BUILD_TIMEOUT  = 900   # seconds  (15 min) — full create.sh run: images + HTML + CSS
SCRAPE_TIMEOUT = 120   # seconds  ( 2 min) — Google Maps Playwright scrape
# =============================================================================

app = FastAPI(title="Review Site Factory & Scraper API")

# ==========================================
# 0. STARTUP VALIDATION
# ==========================================
@app.on_event("startup")
async def validate_environment():
    """Fail fast: check required files and env vars before accepting requests."""
    errors = []

    # --- create.sh ---
    if not os.path.exists("./create.sh"):
        errors.append("create.sh not found in working directory")
    elif not os.access("./create.sh", os.X_OK):
        errors.append("create.sh exists but is not executable (run: chmod +x create.sh)")

    # --- API keys (need at least one for image generation) ---
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    if not has_gemini and not has_openrouter:
        errors.append("Neither GEMINI_API_KEY nor OPENROUTER_API_KEY is set")

    if errors:
        for err in errors:
            print(f"❌ [STARTUP] {err}")
        print("⚠️  [STARTUP] Server started with configuration errors — /generate-site will fail.")
    else:
        key_info = []
        if has_gemini:     key_info.append("GEMINI_API_KEY ✅")
        if has_openrouter: key_info.append("OPENROUTER_API_KEY ✅")
        print(f"✅ [STARTUP] Environment OK — {', '.join(key_info)}")
        print(f"✅ [STARTUP] create.sh found and executable")

    if REMOTE_SITE_URL:
        print(f"🌐 [STARTUP] REMOTE_SITE_URL = {REMOTE_SITE_URL}")
        print(f"             Sites will be served at: {REMOTE_SITE_URL}/<slug>/index.html")
    else:
        print("ℹ️  [STARTUP] REMOTE_SITE_URL not set — site URLs will use local path only.")
        print("             Set REMOTE_SITE_URL in .env or environment to expose public URLs.")

# ==========================================
# 1. DATA MODELS
# ==========================================
class BusinessData(BaseModel):
    business_name: str
    niche: str
    address: str
    tel: str
    webhook_url: str  # For n8n asynchronous callback

def clean_google_text(text: str) -> str:
    if not text:
        return ""
    
    # 1. Strip out the specific Google Private Use Unicode characters
    # (This safely removes \ue0c8, \ue0b0, etc. without breaking normal text)
    cleaned = "".join(c for c in text if not (0xE000 <= ord(c) <= 0xF8FF))
    
    # 2. Strip away the leftover newline (\n) and extra spaces
    return cleaned.strip()

# ==========================================
# 2. THE GENERATOR (Background Task)
# ==========================================

def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    """Kill the entire process group so no orphaned gemini/uv children linger."""
    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGKILL)
        print(f"🔪 [BACKGROUND] Killed process group {pgid}")
    except ProcessLookupError:
        pass  # Already dead — that's fine
    except Exception as kill_err:
        print(f"⚠️ [BACKGROUND] Could not kill process group: {kill_err}")
        # Fallback: kill just the direct child
        try:
            process.kill()
        except Exception:
            pass

def _site_slug(name: str) -> str:
    """Mirror create.sh slug logic: lowercase, spaces→hyphens, strip non-alnum-hyphen."""
    s = name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


async def build_site_and_notify(data: BusinessData):
    script_path = "./create.sh"
    process = None
    try:
        print(f"⚙️ [BACKGROUND] Starting build for: {data.business_name} "
              f"(timeout: {BUILD_TIMEOUT // 60}m)")

        # start_new_session=True puts create.sh in its own process group so we
        # can kill the whole tree (bash → gemini → uv → python …) at once.
        process = await asyncio.create_subprocess_exec(
            script_path, data.business_name, data.niche, data.address, data.tel,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        # Wait for completion with a hard ceiling
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=BUILD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"⏰ [BACKGROUND] Timeout ({BUILD_TIMEOUT // 60}m) hit for: "
                  f"{data.business_name} — killing process group")
            _kill_process_group(process)
            payload = {
                "status": "timeout",
                "business_name": data.business_name,
                "error": f"Build exceeded {BUILD_TIMEOUT // 60}-minute timeout and was killed.",
            }
            async with httpx.AsyncClient() as client:
                await client.post(data.webhook_url, json=payload)
            return

        if process.returncode == 0:
            print(f"✅ [BACKGROUND] Success: {data.business_name}")
            site_slug = _site_slug(data.business_name)
            payload: dict = {"status": "success", "business_name": data.business_name}
            if REMOTE_SITE_URL:
                payload["site_url"] = f"{REMOTE_SITE_URL}/{site_slug}/index.html"
            else:
                payload["site_slug"] = site_slug
        else:
            err_text = stderr.decode(errors="replace").strip()
            print(f"❌ [BACKGROUND] Failed (exit {process.returncode}): {err_text}")
            payload = {"status": "error", "error": err_text}

        # Send result back to n8n Webhook
        async with httpx.AsyncClient() as client:
            await client.post(data.webhook_url, json=payload)

    except Exception as e:
        print(f"🔥 [BACKGROUND] Unexpected error: {e}")
        if process is not None:
            _kill_process_group(process)
        async with httpx.AsyncClient() as client:
            await client.post(data.webhook_url, json={"status": "error", "error": str(e)})

@app.post("/generate-site")
async def generate_site(data: BusinessData, background_tasks: BackgroundTasks):
    if not os.path.exists("./create.sh"):
        raise HTTPException(status_code=500, detail="create.sh not found on server")

    # Add to background queue and return instantly
    background_tasks.add_task(build_site_and_notify, data)

    site_slug = _site_slug(data.business_name)
    response: dict = {
        "status": "processing",
        "message": "Job added to queue.",
        "site_slug": site_slug,
    }
    if REMOTE_SITE_URL:
        response["site_url"] = f"{REMOTE_SITE_URL}/{site_slug}/index.html"

    return response


# ==========================================
# 3. BUILD LOG READER
# ==========================================

def _parse_build_stats(log_text: str) -> dict:
    """
    Extract key metrics from the build.log stats block.
    Returns a dict; missing fields are simply omitted.
    """
    stats: dict = {}

    m = re.search(r"Total time:\s+([\d]+m\s+[\d]+s)", log_text)
    if m: stats["total_time"] = m.group(1).strip()

    m = re.search(r"Mode:\s+(\w+)\s+\(([^)]+)\)", log_text)
    if m: stats["mode"] = f"{m.group(1)} ({m.group(2).strip()})"

    m = re.search(r"Generated:\s+(\d+)\s*/\s*(\d+)", log_text)
    if m:
        stats["images_generated"] = int(m.group(1))
        stats["images_total"]     = int(m.group(2))

    m = re.search(r"Failed:\s+(\d+)", log_text)
    if m: stats["images_failed"] = int(m.group(1))

    m = re.search(r"Total:\s+~?\$?([\d.]+)", log_text)
    if m: stats["estimated_cost_usd"] = float(m.group(1))

    m = re.search(r"Assets size:\s+(\S+)", log_text)
    if m: stats["assets_size"] = m.group(1).strip()

    m = re.search(r"Total size:\s+(\S+)", log_text)
    if m: stats["total_size"] = m.group(1).strip()

    # Final public URL written by create.sh: "🌐 Open: http://..."
    m = re.search(r"Open:\s+(https?://\S+)", log_text)
    if m: stats["site_url"] = m.group(1).strip()

    return stats


@app.get("/build-log/{slug}")
async def get_build_log(slug: str, lines: int = 0):
    """
    Return the build log and parsed stats for a generated site.

    - **slug**  — site slug, e.g. `luigi-hair-salon`
    - **lines** — if > 0, only the last N lines of the raw log are returned
                  (useful to tail a running build); default 0 = full log
    """
    log_path = os.path.join("sites", slug, "build.log")
    if not os.path.exists(log_path):
        raise HTTPException(
            status_code=404,
            detail=f"No build.log for '{slug}'. Build may not have started yet."
        )

    with open(log_path, "r", errors="replace") as f:
        full_log = f.read()

    raw = "\n".join(full_log.splitlines()[-lines:]) if lines > 0 else full_log

    # Detect state from the tail of the log
    tail = full_log[-2000:]
    if "🌐 Open:" in tail:
        build_status = "complete"
    elif "❌ Failed" in tail or "exit 1" in tail:
        build_status = "failed"
    else:
        build_status = "in_progress"

    return {
        "slug":         slug,
        "build_status": build_status,
        "stats":        _parse_build_stats(full_log),
        "log":          raw,
    }


# ==========================================
# 4. THE SCRAPER (Playwright)
# ==========================================

async def _do_scrape(query: str, max_results: int) -> dict:
    """Inner scrape logic — called inside a wait_for timeout wrapper."""
    results = []

    async with async_playwright() as p:
        # --no-sandbox is required for root/VPS environments without a GUI
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )

        # Inject the Google Consent Cookie to bypass the EU/Italy popup instantly.
        context = await browser.new_context()
        await context.add_cookies([{
            "name": "SOCS",
            "value": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzEaAmVuIAEaBgiA_LyaBg",
            "domain": ".google.com",
            "path": "/"
        }])

        page = await context.new_page()

        safe_query = urllib.parse.quote_plus(query)
        # hl= keeps results in the configured language; cookie stops consent popup
        url = f"https://www.google.com/maps/search/{safe_query}?hl={SITE_LANG}"

        print(f"🕵️ Scraping Maps for: {query}")
        await page.goto(url)

        # Wait for the listing feed to appear
        try:
            await page.wait_for_selector(
                'a[href^="https://www.google.com/maps/place"]', timeout=10000
            )
        except Exception:
            await browser.close()
            return {"status": "error", "message": "Could not find listings. Google might be blocking or DOM changed."}

        listings = await page.locator('a[href^="https://www.google.com/maps/place"]').all()

        for i in range(min(max_results, len(listings))):
            listing = listings[i]

            # Click to open the detail panel
            await listing.click()
            await page.wait_for_timeout(2500)  # sidebar animation

            name, phone, website, address = "", "", "", ""

            try:
                name = await page.locator('h1.DUwDvf').first.inner_text()
            except: pass

            try:
                niche_element = page.locator('button.DkEaL').first
                raw_niche = await niche_element.inner_text()
                niche = clean_google_text(raw_niche)
            except:
                # Fallback: use first word of the search query
                niche = query.split(" ")[0]

            try:
                address_element = page.locator(
                    'button[data-tooltip*="indirizzo" i], button[data-tooltip*="address" i]'
                ).first
                address = clean_google_text(await address_element.inner_text())
            except: pass

            try:
                phone_element = page.locator(
                    'button[data-tooltip*="telefono" i], button[data-tooltip*="phone" i]'
                ).first
                phone = clean_google_text(await phone_element.inner_text())
            except: pass

            try:
                website_element = page.locator(
                    'a[data-tooltip*="sito" i], a[data-tooltip*="website" i]'
                ).first
                website = await website_element.get_attribute('href')
            except: pass

            if name:
                results.append({
                    "business_name": name,
                    "niche": niche,
                    "address": address,
                    "tel": phone,
                    "website": website
                })

        await browser.close()

    return {"status": "success", "data": results}


@app.get("/scrape-maps")
async def scrape_google_maps(
    query: str = "",
    business_type: str = "",
    location: str = "",
    max_results: int = 5,
):
    """
    Scrape Google Maps listings.

    You can call this two ways:

    **1. Raw query** (backward-compatible):
        GET /scrape-maps?query=parrucchiere+la+spezia

    **2. Structured params** (recommended — auto-encodes correctly):
        GET /scrape-maps?business_type=parrucchiere&location=la+spezia

    The structured form builds:
        https://www.google.com/maps/search/parrucchiere+la+spezia?hl={SITE_LANG}

    SITE_LANG env var controls the `hl=` parameter (default: it).
    """
    if not query and not (business_type and location):
        raise HTTPException(
            status_code=422,
            detail="Provide either 'query' OR both 'business_type' and 'location'."
        )

    # Build canonical query string from structured params when available
    if business_type and location:
        # e.g. "pizza restaurant" + "la spezia" → "pizza restaurant la spezia"
        combined = f"{business_type.strip()} {location.strip()}"
        effective_query = combined
    else:
        effective_query = query.strip()

    print(f"🕵️ [SCRAPE] query='{effective_query}'  lang={SITE_LANG}  max_results={max_results}  timeout={SCRAPE_TIMEOUT}s")
    try:
        return await asyncio.wait_for(
            _do_scrape(effective_query, max_results),
            timeout=SCRAPE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"⏰ [SCRAPE] Timeout ({SCRAPE_TIMEOUT}s) hit for query: '{effective_query}'")
        raise HTTPException(
            status_code=504,
            detail=f"Scrape timed out after {SCRAPE_TIMEOUT // 60} minutes. "
                   "Google Maps may be slow or blocking the request."
        )
