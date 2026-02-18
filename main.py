from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
import urllib.parse
import asyncio
import signal
import httpx
import os

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
            payload = {"status": "success", "business_name": data.business_name}
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
    return {"status": "processing", "message": "Job added to queue."}


# ==========================================
# 3. THE SCRAPER (Playwright)
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
        # hl=it keeps results in Italian; the cookie stops the consent popup
        url = f"https://www.google.com/maps/search/{safe_query}?hl=it"

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
async def scrape_google_maps(query: str, max_results: int = 5):
    print(f"🕵️ [SCRAPE] query='{query}' max_results={max_results} timeout={SCRAPE_TIMEOUT}s")
    try:
        return await asyncio.wait_for(
            _do_scrape(query, max_results),
            timeout=SCRAPE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"⏰ [SCRAPE] Timeout ({SCRAPE_TIMEOUT}s) hit for query: '{query}'")
        raise HTTPException(
            status_code=504,
            detail=f"Scrape timed out after {SCRAPE_TIMEOUT // 60} minutes. "
                   "Google Maps may be slow or blocking the request."
        )
