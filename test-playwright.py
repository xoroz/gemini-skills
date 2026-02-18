import asyncio
from playwright.async_api import async_playwright

async def main():
    print("🚀 Starting Playwright test...")
    
    async with async_playwright() as p:
        try:
            # The --no-sandbox argument is critical for running as root/VPS
            print("⏳ Launching headless Chromium...")
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            
            page = await browser.new_page()
            
            print("🌐 Navigating to example.com...")
            await page.goto("http://example.com")
            
            title = await page.title()
            print(f"✅ Success! Loaded page title: '{title}'")
            
            print("📸 Taking a screenshot (test_shot.png)...")
            await page.screenshot(path="test_shot.png")
            
            await browser.close()
            print("🏁 Test finished successfully.")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            raise SystemExit(1)

if __name__ == "__main__":
    asyncio.run(main())
