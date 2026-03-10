from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright
import re
import urllib.parse
import asyncio
import signal
import httpx
import os
import logging
import json
from logging.handlers import RotatingFileHandler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ---------------------------------------------------------------------------
# Setup Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# -- Main Backend Logger --
logger = logging.getLogger("backend")
logger.setLevel(logging.DEBUG)

fh = RotatingFileHandler("logs/backend.log", maxBytes=5*1024*1024, backupCount=2)
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)

# -- Dedicated Scraper Logger --
# To avoid polluting backend.log with Maps JS errors
scrape_logger = logging.getLogger("scraper")
scrape_logger.setLevel(logging.DEBUG)

sfh = RotatingFileHandler("logs/scrape.log", maxBytes=5*1024*1024, backupCount=2)
sfh.setLevel(logging.DEBUG)
sfh.setFormatter(formatter)
scrape_logger.addHandler(sfh)
scrape_logger.addHandler(ch)  # Also print to terminal

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
BUILD_TIMEOUT  = int(os.environ.get("BUILD_TIMEOUT", "900"))   # seconds (15 min) — full create.sh run: images + HTML + CSS
SCRAPE_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT", "120"))  # seconds ( 2 min) — Google Maps Playwright scrape
# =============================================================================

# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI metadata
# ---------------------------------------------------------------------------
_description = """
## Review Site Factory & Scraper API

Automates the creation of local-business review landing pages and Google Maps scraping.

### Workflow
1. **Scrape** — call `/scrape-maps` to discover businesses in any niche & location.
2. **Generate** — call `/generate-site` with the business data; a background job runs
   `create.sh` (Gemini images + HTML/CSS) and POSTs the result to your `webhook_url`.
3. **Monitor** — poll `/build-log/{slug}` to tail the live log and check build status.

### Notes
- Requires `GEMINI_API_KEY` **or** `OPENROUTER_API_KEY` in the environment.
- Set `REMOTE_SITE_URL` so response payloads include the public site URL.
- Build timeout: 15 minutes per site (configurable via `BUILD_TIMEOUT`).
"""

_tags_metadata = [
    {
        "name": "sites",
        "description": "Generate AI-powered landing pages for local businesses.",
    },
    {
        "name": "logs",
        "description": "Inspect build logs and parsed statistics for generated sites.",
    },
    {
        "name": "scraping",
        "description": "Scrape Google Maps to discover business leads.",
    },
]

app = FastAPI(
    title="Review Site Factory & Scraper API",
    description=_description,
    version="1.0.0",
    root_path=os.environ.get("OPENAPI_ROOT_PATH", "/api"), # Needed for proxy routing
    contact={
        "name": "Auto-Sites",
        "url": "https://github.com/xoroz/gemini-skills",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=_tags_metadata,
    docs_url="/docs",      # Swagger UI  — default, explicit for clarity
    redoc_url="/redoc",   # ReDoc       — alternative, cleaner read view
)

# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Security: Static Bearer Token
# ---------------------------------------------------------------------------
API_TOKEN = os.environ.get("API_TOKEN", "")
bearer_scheme = HTTPBearer(auto_error=False)

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if API_TOKEN:
        if not credentials or credentials.credentials != API_TOKEN:
            logger.warning("Unauthorized access attempt with invalid token.")
            raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
    return credentials

# ---------------------------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health_check():
    """Simple health check endpoint for monitoring."""
    return {"status": "ok", "version": "1.0.0"}

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
            logger.error(f"❌ [STARTUP] {err}")
        logger.warning("⚠️  [STARTUP] Server started with configuration errors — /generate-site will fail.")
    else:
        key_info = []
        if has_gemini:     key_info.append("GEMINI_API_KEY ✅")
        if has_openrouter: key_info.append("OPENROUTER_API_KEY ✅")
        logger.info(f"✅ [STARTUP] Environment OK — {', '.join(key_info)}")
        logger.info(f"✅ [STARTUP] create.sh found and executable")

    if REMOTE_SITE_URL:
        logger.info(f"🌐 [STARTUP] REMOTE_SITE_URL = {REMOTE_SITE_URL}")
        logger.info(f"             Sites will be served at: {REMOTE_SITE_URL}/<slug>/index.html")
    else:
        logger.info("ℹ️  [STARTUP] REMOTE_SITE_URL not set — site URLs will use local path only.")
        logger.info("             Set REMOTE_SITE_URL in .env or environment to expose public URLs.")

# ==========================================
# 1. DATA MODELS
# ==========================================
class BusinessData(BaseModel):
    business_name: str
    niche: str
    address: str
    tel: str
    webhook_url: str  # For n8n asynchronous callback

class ModifySiteData(BaseModel):
    site_slug: str
    target_selector: str
    prompt: str

class CreateFlyersData(BaseModel):
    qnt: int

class AssignSiteData(BaseModel):
    site_id: str
    site_slug: str

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
        logger.info(f"🔪 [BACKGROUND] Killed process group {pgid}")
    except ProcessLookupError:
        pass  # Already dead — that's fine
    except Exception as kill_err:
        logger.warning(f"⚠️ [BACKGROUND] Could not kill process group: {kill_err}")
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


async def _take_screenshot(site_slug: str):
    """Take a screenshot of the generated site using Playwright and save it."""
    index_file = os.path.join("sites", site_slug, "index.html")
    screenshot_path = os.path.join("sites", site_slug, "screenshot.png")
    
    if not os.path.exists(index_file):
        return
        
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            
            abs_path = os.path.abspath(index_file)
            await page.goto(f"file://{abs_path}", wait_until="networkidle", timeout=15000)
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.info(f"📸 [BACKGROUND] Screenshot saved for '{site_slug}' at {screenshot_path}")
            await browser.close()
    except Exception as e:
        logger.warning(f"⚠️ [BACKGROUND] Failed to take screenshot for '{site_slug}': {e}")


async def _post_webhook(webhook_url: str, payload: dict, label: str, initial_delay: float = 0.0) -> None:
    """
    POST payload to webhook_url exactly once.

    n8n holds the HTTP connection open until its entire workflow finishes,
    which can be 30s–several minutes. We therefore use:
      - connect_timeout = 10s  (catch wrong URL / network down quickly)
      - read_timeout    = None  (wait as long as n8n needs; we don't need its response body)

    initial_delay — seconds to wait before the attempt.
                    Use this for cache-hit paths where n8n's Wait node
                    may not have finished registering its listener yet.
    """
    if initial_delay > 0:
        logger.info(f"⏳ [WEBHOOK] Waiting {initial_delay}s before calling {label} webhook (race-condition guard)")
        await asyncio.sleep(initial_delay)

    # connect_timeout catches bad URLs / network issues fast.
    # read_timeout=None: n8n keeps the connection alive until its workflow completes —
    # we must not time out waiting for it; we only care that the POST was delivered.
    _timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=5.0)

    try:
        async with httpx.AsyncClient(timeout=_timeout) as client:
            logger.info(f"📤 [WEBHOOK] Posting to {label}...")
            r = await client.post(webhook_url, json=payload)
            if r.status_code < 400:
                logger.info(f"✅ [WEBHOOK] {label} → HTTP {r.status_code}")
            else:
                logger.warning(
                    f"⚠️ [WEBHOOK] {label} → HTTP {r.status_code}: {r.text[:200]}"
                )
    except Exception as exc:
        logger.error(
            f"❌ [WEBHOOK] {label} → failed: {type(exc).__name__}: {exc!r}"
        )



def _lookup_site_id(slug: str) -> dict | None:
    """Look up a slug in sites/site-id.json and return its entry if found."""
    registry_path = os.path.join("sites", "site-id.json")
    if not os.path.exists(registry_path):
        return None
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        for entry in registry:
            if entry.get("slug") == slug:
                return entry
    except (json.JSONDecodeError, OSError):
        pass
    return None


async def build_site_and_notify(data: BusinessData):
    site_slug = _site_slug(data.business_name)
    site_dir = os.path.join("sites", site_slug)
    index_file = os.path.join(site_dir, "index.html")
    css_file = os.path.join(site_dir, "style.css")

    # Check if files exist and are not empty
    if os.path.exists(index_file) and os.path.getsize(index_file) > 0 and \
       os.path.exists(css_file) and os.path.getsize(css_file) > 0:
        logger.info(f"⏭️ [BACKGROUND] Site '{site_slug}' already exists and is complete. Skipping build.")
        payload: dict = {"status": "success", "business_name": data.business_name}
        if REMOTE_SITE_URL:
            payload["site_url"] = f"{REMOTE_SITE_URL}/{site_slug}/index.html"
        else:
            payload["site_slug"] = site_slug

        # Look up site_id from registry for cache-hit payloads
        id_info = _lookup_site_id(site_slug)
        if id_info:
            payload["site_id"] = id_info["id"]
            payload["url_id"] = id_info.get("url_id", "")

        # Delay before firing: n8n's Wait node needs ~1-2s to register its listener
        # after the /generate-site response is received. Cache hits are instant,
        # so without this delay the webhook fires before n8n is ready.
        await _post_webhook(data.webhook_url, payload, f"cache-hit/{site_slug}", initial_delay=2.0)
        return

    script_path = "./create.sh"
    process = None
    try:
        logger.info(f"⚙️ [BACKGROUND] Starting build for: {data.business_name} "
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
            logger.warning(f"⏰ [BACKGROUND] Timeout ({BUILD_TIMEOUT // 60}m) hit for: "
                  f"{data.business_name} — killing process group")
            _kill_process_group(process)
            payload = {
                "status": "timeout",
                "business_name": data.business_name,
                "error": f"Build exceeded {BUILD_TIMEOUT // 60}-minute timeout and was killed.",
            }
            await _post_webhook(data.webhook_url, payload, f"timeout/{site_slug}")
            return

        if process.returncode == 0:
            logger.info(f"✅ [BACKGROUND] Success: {data.business_name}")
            
            await _take_screenshot(site_slug)
            
            payload: dict = {"status": "success", "business_name": data.business_name}
            if REMOTE_SITE_URL:
                payload["site_url"] = f"{REMOTE_SITE_URL}/{site_slug}/index.html"
            else:
                payload["site_slug"] = site_slug

            # Parse site_id/url_id from build output
            build_output = stdout.decode(errors="replace")
            m_id = re.search(r"SITE_ID=(\S+)", build_output)
            m_urlid = re.search(r"URLID=(\S+)", build_output)
            if m_id:
                payload["site_id"] = m_id.group(1)
            if m_urlid:
                payload["url_id"] = m_urlid.group(1)
        else:
            err_text = stderr.decode(errors="replace").strip()
            logger.error(f"❌ [BACKGROUND] Failed (exit {process.returncode}): {err_text}")
            payload = {"status": "error", "error": err_text}

        # Send result back to n8n Webhook
        await _post_webhook(data.webhook_url, payload, f"build/{site_slug}")

    except Exception as e:
        logger.error(f"🔥 [BACKGROUND] Unexpected error: {e}")
        if process is not None:
            _kill_process_group(process)
        await _post_webhook(
            data.webhook_url,
            {"status": "error", "error": str(e)},
            f"exception/{site_slug}",
        )

@app.post("/generate-site", dependencies=[Depends(verify_token)], tags=["sites"])
async def generate_site(data: BusinessData, background_tasks: BackgroundTasks):
    if not os.path.exists("./create.sh"):
        raise HTTPException(status_code=500, detail="create.sh not found on server")

    # Add to background queue and return instantly
    background_tasks.add_task(build_site_and_notify, data)

    site_slug = _site_slug(data.business_name)
    response: dict = {
        "status": "processing",
        "message": "Job added to queue.",
        "job_id": site_slug,
        "site_slug": site_slug,
    }
    if REMOTE_SITE_URL:
        response["site_url"] = f"{REMOTE_SITE_URL}/{site_slug}/index.html"

    # Pre-allocate short ID so n8n gets it immediately
    id_info = _lookup_site_id(site_slug)
    if id_info:
        response["site_id"] = id_info["id"]
        response["url_id"] = id_info.get("url_id", "")
    else:
        # Allocate now via id_manager (create.sh will reuse the same ID)
        try:
            import subprocess
            result = subprocess.run(
                ["uv", "run", "scripts/id_manager.py", "allocate",
                 "--business", data.business_name,
                 "--remote-url", REMOTE_SITE_URL or ""],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    if line.startswith("SITE_ID="):
                        response["site_id"] = line.split("=", 1)[1]
                    elif line.startswith("URLID="):
                        response["url_id"] = line.split("=", 1)[1]
        except Exception as exc:
            logger.warning(f"⚠️ [GENERATE] Could not pre-allocate ID: {exc}")

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

    # Final public URL written by create.sh: "🌐 URL=http://..."
    m = re.search(r"URL=(https?://\S+)", log_text)
    if m: stats["site_url"] = m.group(1).strip()

    # Short ID system
    m = re.search(r"URLID=(\S+)", log_text)
    if m: stats["url_id"] = m.group(1).strip()

    m = re.search(r"SITE_ID=(\S+)", log_text)
    if m: stats["site_id"] = m.group(1).strip()

    return stats


@app.get("/build-log/{slug}", dependencies=[Depends(verify_token)], tags=["logs"])
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
    if "🌐 URL=" in tail:
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

@app.get("/status/{job_id}", dependencies=[Depends(verify_token)], tags=["sites"])
async def get_job_status(job_id: str):
    """
    Check the status of a site generation job using its job_id (which is its slug).
    Returns the state without the full raw log (lighter than /build-log).
    """
    log_path = os.path.join("sites", job_id, "build.log")
    index_file = os.path.join("sites", job_id, "index.html")
    css_file = os.path.join("sites", job_id, "style.css")

    # If already built (check cache-like files)
    if os.path.exists(index_file) and os.path.getsize(index_file) > 0 and \
       os.path.exists(css_file) and os.path.getsize(css_file) > 0:
        stats = {}
        if os.path.exists(log_path):
            with open(log_path, "r", errors="replace") as f:
                stats = _parse_build_stats(f.read())
        return {
            "job_id": job_id,
            "status": "complete",
            "message": "Site is fully built and ready.",
            "stats": stats
        }

    # Otherwise parse the log to find state
    if not os.path.exists(log_path):
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Job hasn't started yet or cannot be found."
        }

    with open(log_path, "r", errors="replace") as f:
        full_log = f.read()

    tail = full_log[-2000:]
    if "🌐 URL=" in tail:
        status = "complete"
    elif "❌ Failed" in tail or "exit 1" in tail:
        status = "failed"
    else:
        status = "in_progress"

    return {
        "job_id": job_id,
        "status": status,
        "stats": _parse_build_stats(full_log)
    }


# ==========================================
# 4. THE SCRAPER (Playwright)
# ==========================================

# Use a Semaphore to ensure we only run 1 Chrome instance at a time for scraping.
# n8n might send 5 requests at once; this queues them neatly so the VPS doesn't crash.
scrape_semaphore = asyncio.Semaphore(1)

async def _do_scrape(query: str, max_results: int) -> dict:
    """Inner scrape logic — called inside a wait_for timeout wrapper."""
    results = []

    async with scrape_semaphore:
        scrape_logger.info(f"🚦 Acquired scraper lock. Starting browser for: {query}")
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

            scrape_logger.info(f"🕵️ Scraping Maps for: {query} (URL: {url})")
            await page.goto(url)
            scrape_logger.info(f"✅ Page loaded. Waiting for listings to appear...")

            # Dump any browser console errors to our backend log (helpful if maps throws JS errors)
            page.on("console", lambda msg: scrape_logger.debug(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))

            # Wait for the listing feed to appear
            try:
                await page.wait_for_selector(
                    'a[href^="https://www.google.com/maps/place"]', timeout=10000
                )
            except Exception as e:
                error_screenshot = os.path.join("logs", "scrape_error.png")
                await page.screenshot(path=error_screenshot, full_page=True)
                scrape_logger.error(f"❌ [SCRAPE] Failed to find listings for '{query}'. Screenshot saved to {error_screenshot}. Error: {e}")
                await browser.close()
                return {"status": "error", "message": f"Could not find listings. Google might be blocking or DOM changed. See {error_screenshot}"}

            listings = await page.locator('a[href^="https://www.google.com/maps/place"]').all()
            found_count = len(listings)
            scrape_logger.info(f"✅ Found {found_count} listing elements. Extracting up to {max_results}...")

            for i in range(min(max_results, found_count)):
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
                    scrape_logger.debug(f"ℹ️ Extracted [{i+1}/{max_results}]: {name} | {phone}")
                    results.append({
                        "business_name": name,
                        "niche": niche,
                        "address": address,
                        "tel": phone,
                        "website": website
                    })
                else:
                    scrape_logger.warning(f"⚠️ Listing {i+1} failed to extract a business name.")

            await browser.close()
            scrape_logger.info(f"🚦 Releasing scraper lock for: {query}. Successfully extracted {len(results)} items.")

    return {"status": "success", "data": results}


def _get_cache_path(query: str, max_results: int) -> str:
    """Generate a safe, unique filename for a search query + quantity cache.

    max_results is included in the key so that a cache entry for N results
    is never served to a request asking for more than N.
    """
    import hashlib
    safe_name = re.sub(r"[^a-z0-9]", "_", query.lower())
    # Include max_results in the hash so different quantities get separate files
    hash_input = f"{query}|max={max_results}"
    hash_suffix = hashlib.md5(hash_input.encode()).hexdigest()[:8]

    os.makedirs(".cache", exist_ok=True)
    return os.path.join(".cache", f"scrape_{safe_name}_n{max_results}_{hash_suffix}.json")


@app.get("/scrape-maps", dependencies=[Depends(verify_token)], tags=["scraping"])
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

    # --- Cache Check ---
    # Key includes max_results so a cache with fewer items never silently
    # satisfies a request that asked for more.
    cache_file = _get_cache_path(effective_query, max_results)
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            cached_items = cached_data.get("data", [])
            if len(cached_items) >= max_results:
                # Slice to exactly what was requested (cache may contain more
                # if a larger query was saved earlier under the same hash).
                cached_data["data"] = cached_items[:max_results]
                scrape_logger.info(
                    f"⚡ [SCRAPE] Cache hit for '{effective_query}' "
                    f"({len(cached_data['data'])}/{max_results} results). Returning cached results."
                )
                return cached_data
            else:
                scrape_logger.info(
                    f"⚡ [SCRAPE] Cache stale for '{effective_query}': "
                    f"has {len(cached_items)} results but {max_results} requested — running fresh scrape."
                )
        except Exception as e:
            scrape_logger.warning(f"⚠️ [SCRAPE] Failed to read cache file {cache_file}: {e}")

    scrape_logger.info(f"🕵️ [SCRAPE] query='{effective_query}'  lang={SITE_LANG}  max_results={max_results}  timeout={SCRAPE_TIMEOUT}s")
    try:
        result = await asyncio.wait_for(
            _do_scrape(effective_query, max_results),
            timeout=SCRAPE_TIMEOUT,
        )
        # --- Save to Cache ---
        if result.get("status") == "success" and result.get("data"):
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            except Exception as e:
                scrape_logger.warning(f"⚠️ [SCRAPE] Failed to write cache file {cache_file}: {e}")

        return result
    except asyncio.TimeoutError:
        scrape_logger.warning(f"⏰ [SCRAPE] Timeout ({SCRAPE_TIMEOUT}s) hit for query: '{effective_query}'")
        raise HTTPException(
            status_code=504,
            detail=f"Scrape timed out after {SCRAPE_TIMEOUT // 60} minutes. "
                   "Google Maps may be slow or blocking the request."
        )

# ==========================================
# 5. SITE EDITOR
# ==========================================

@app.post("/modify-site", dependencies=[Depends(verify_token)], tags=["sites"])
async def modify_site(data: ModifySiteData):
    """
    Modify an AI-generated site by specifying a CSS selector and an AI prompt.
    Runs the modify.sh script and returns the result.
    """
    script_path = "./modify.sh"
    if not os.path.exists(script_path):
        raise HTTPException(status_code=500, detail="modify.sh not found on server")

    # This is a simple POC; we wait for the process to finish
    try:
        logger.info(f"⚙️ [MODIFY] Starting modification for site: {data.site_slug}, selector: {data.target_selector}")
        process = await asyncio.create_subprocess_exec(
            script_path, data.site_slug, data.target_selector, data.prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        
        if process.returncode == 0:
            logger.info(f"✅ [MODIFY] Success for {data.site_slug}")
            return {
                "status": "success",
                "site_slug": data.site_slug,
                "message": "Site successfully modified."
            }
        else:
            err_text = stderr.decode(errors="replace").strip()
            out_text = stdout.decode(errors="replace").strip()
            logger.error(f"❌ [MODIFY] Failed: {err_text} | {out_text}")
            raise HTTPException(status_code=500, detail=f"Modification failed: {err_text}")
            
    except asyncio.TimeoutError:
         logger.warning(f"⏰ [MODIFY] Timeout hit for: {data.site_slug}")
         try:
             process.kill()
         except: pass
         raise HTTPException(status_code=504, detail="Modification timed out.")
    except Exception as e:
         logger.error(f"🔥 [MODIFY] Unexpected error: {e}")
         raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 6. FLYER MANAGER
# ==========================================

async def generate_flyers_bg(current_ids: list[str], remote_url: str):
    """Background task to run make_flyer.py with the new range of IDs."""
    if not current_ids:
        return
        
    start_id = current_ids[0]
    end_id = current_ids[-1]
    id_range = f"{start_id}-{end_id}" if len(current_ids) > 1 else start_id
    
    script_path = "./scripts/make_flyer.py"
    if not os.path.exists(script_path):
        logger.error("❌ [FLYER] make_flyer.py not found on server")
        return
        
    try:
        logger.info(f"⚙️ [FLYER] Starting flyer generation for range: {id_range}")
        process = await asyncio.create_subprocess_exec(
            "uv", "run", script_path, 
            "--site-id", id_range,
            "--force",
            "--remote-url", remote_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        
        if process.returncode == 0:
            logger.info(f"✅ [FLYER] Success for range {id_range}")
            # Try to create symlink for downloads
            try:
                assets_dir = os.path.abspath("assets/flyers")
                sites_flyers = os.path.abspath("sites/flyers")
                if not os.path.exists(sites_flyers) and os.path.exists(assets_dir):
                    os.symlink(assets_dir, sites_flyers)
                    logger.info(f"🔗 [FLYER] Created symlink from {assets_dir} to {sites_flyers}")
            except Exception as e:
                logger.warning(f"⚠️ [FLYER] Failed to create symlink: {e}")
        else:
            err_text = stderr.decode(errors="replace").strip()
            logger.error(f"❌ [FLYER] Failed: {err_text}")
    except asyncio.TimeoutError:
        logger.warning(f"⏰ [FLYER] Timeout hit for range: {id_range}")
        try:
            process.kill()
        except: pass
    except Exception as e:
        logger.error(f"🔥 [FLYER] Unexpected error: {e}")

@app.post("/create-flyers", dependencies=[Depends(verify_token)], tags=["sites"])
async def create_flyers(data: CreateFlyersData, background_tasks: BackgroundTasks):
    """
    Generate new pre-print flyers without overwriting existing ones.
    Allocates new placeholder IDs in the registry.
    """
    if data.qnt <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
        
    if data.qnt > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 flyers per request allowed")
        
    # We will use id_manager's core logic to calculate the next N IDs quickly
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), "scripts"))
    try:
        import id_manager
    except ImportError:
        raise HTTPException(status_code=500, detail="Failed to load id_manager module")
        
    registry = id_manager._load_registry()
    existing_ids = [e["id"] for e in registry if "id" in e]
    
    new_ids = []
    for _ in range(data.qnt):
        nxt = id_manager._next_id(existing_ids)
        new_ids.append(nxt)
        existing_ids.append(nxt)
        
    if not new_ids:
        raise HTTPException(status_code=500, detail="Failed to calculate new IDs")
        
    # The actual generation is passed to background
    remote_url = REMOTE_SITE_URL or "https://dev.texngo.it"
    background_tasks.add_task(generate_flyers_bg, new_ids, remote_url)
    
    return {
        "status": "processing",
        "message": f"Job added to generate {data.qnt} flyers in background.",
        "created_ids": new_ids,
        "range": f"{new_ids[0]}-{new_ids[-1]}" if len(new_ids) > 1 else new_ids[0]
    }

@app.post("/assign-site", dependencies=[Depends(verify_token)], tags=["sites"])
async def assign_site(data: AssignSiteData):
    """
    Assign an existing pre-printed site ID to an actual generated site.
    Validates that the site directory exists and updates the registry.
    """
    site_dir = os.path.join("sites", data.site_slug)
    if not os.path.exists(site_dir) or not os.path.isdir(site_dir):
        raise HTTPException(status_code=404, detail=f"Site directory for '{data.site_slug}' not found.")
        
    remote_url = REMOTE_SITE_URL or "https://dev.texngo.it"
    
    try:
        import subprocess
        result = subprocess.run(
            ["uv", "run", "scripts/id_manager.py", "update",
             "--id", data.site_id,
             "--slug", data.site_slug,
             "--remote-url", remote_url],
            capture_output=True, text=True, timeout=10, env=os.environ.copy()
        )
        if result.returncode == 0:
            return {
                "status": "success",
                "message": f"Successfully assigned ID {data.site_id} to slug '{data.site_slug}'.",
                "output": result.stdout.strip()
            }
        else:
            logger.error(f"❌ [ASSIGN] id_manager failed: {result.stderr}")
            raise HTTPException(status_code=400, detail=f"Failed to assign: {result.stderr.strip()}")
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Operation timed out")
    except Exception as e:
        logger.error(f"🔥 [ASSIGN] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 7. REDIRECT DIRECT SITE IDs (e.g. 00A.html)
# ==========================================

@app.get("/{filename}", tags=["redirect"])
async def redirect_site(filename: str):
    """
    Redirects https://dev.texngo.it/00A.html to the generated site url dynamically.
    Checks the registry for the given ID.
    """
    import re
    if not re.match(r"^[A-Z0-9]{3}\.html$", filename, re.IGNORECASE):
        raise HTTPException(status_code=404, detail="Not found")
        
    site_id = filename[:3].upper()
    
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), "scripts"))
    try:
        import id_manager
    except ImportError:
        logger.error("❌ [REDIRECT] Failed to load id_manager module")
        raise HTTPException(status_code=500, detail="Internal configuration error")
        
    registry = id_manager._load_registry()
    for entry in registry:
        if entry.get("id", "").upper() == site_id:
            target_url = entry.get("url")
            if target_url:
                # If target_url is relative, we prepend REMOTE_SITE_URL
                if target_url.startswith("http"):
                    return RedirectResponse(url=target_url, status_code=302)
                else:
                    base = REMOTE_SITE_URL or "https://dev.texngo.it"
                    return RedirectResponse(url=f"{base.rstrip('/')}/{target_url}", status_code=302)
            else:
                # Placeholder, not assigned yet or waiting for generation
                raise HTTPException(status_code=404, detail=f"Site {site_id} is reserved but not active yet.")
                
    raise HTTPException(status_code=404, detail=f"Site ID {site_id} not found.")
