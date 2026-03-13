# Scraper System

Complete reference for `scripts/scrape_site.py` — the Playwright-based website scraper that powers the **frontend-clone** workflow.

---

## What It Does

Given a business website URL, the scraper:

1. **Loads the page** in a headless Chromium browser (via Playwright)
2. **Dismisses cookie/GDPR banners** automatically
3. **Scrolls** to trigger lazy-loaded content
4. **Extracts** structured data using in-browser JavaScript evaluation
5. **Saves** two output files per domain:
   - `scrapes/<domain>/data.json` — machine-readable structured schema
   - `scrapes/<domain>/raw.md` — human-readable markdown summary (injected into the AI prompt)
6. **Screenshots** the full page as `scrapes/<domain>/screenshot.png`

---

## Workflow: Scrape → Clone

The scraper is the first step of the `frontend-clone` pipeline. The full workflow:

```
  ┌───────────────────────────────────────────────────────────┐
  │ 1. User provides WEBSITE_URL when calling create.sh        │
  │    WEBSITE_URL=https://client-site.it ./create.sh ...      │
  ├───────────────────────────────────────────────────────────┤
  │ 2. create.sh runs scrape_site.py on the URL               │
  │    → scrapes/<domain>/data.json (structured schema)        │
  │    → scrapes/<domain>/raw.md    (AI-readable summary)      │
  │    → scrapes/<domain>/screenshot.png                       │
  ├───────────────────────────────────────────────────────────┤
  │ 3. raw.md is injected into the AI prompt as               │
  │    "REAL BUSINESS DATA (scraped from ...)"                 │
  │    → AI uses real name, address, phone, colors, services   │
  ├───────────────────────────────────────────────────────────┤
  │ 4. AI generates HTML using frontend-clone skill           │
  │    (which extends frontend-design with real scraped data)  │
  ├───────────────────────────────────────────────────────────┤
  │ 5. Site is built with real content, no placeholder text   │
  └───────────────────────────────────────────────────────────┘
```

### Running the scraper directly

```bash
source venv/bin/activate
python scripts/scrape_site.py "https://www.example.com"

# Custom output directory:
python scripts/scrape_site.py "https://www.example.com" --out /tmp/scrapes
```

### Triggering via create.sh

```bash
WEBSITE_URL=https://client-site.it ./create.sh "Business Name" "niche" "address" "tel"
```

When `WEBSITE_URL` is set, `create.sh` switches from the `frontend-design` skill to the `frontend-clone` skill, which instructs the AI to use real scraped data rather than invented placeholder content.

---

## Output Files

All outputs are saved under `scrapes/<domain>/`:

| File | Contents |
|---|---|
| `data.json` | Structured JSON — strictly the schema, no extra fields |
| `raw.md` | Markdown summary — includes extra fields for AI context |
| `screenshot.png` | Full-page screenshot (1280 px wide) |

The `scrapes/` directory is **not committed** to git (listed in `.gitignore`).

---

## JSON Schema (`data.json`)

```json
{
  "site_url": "https://example.com/",
  "metadata": {
    "title": "",
    "description": "",
    "favicon_url": "",
    "language": ""
  },
  "branding": {
    "logo_url": "",
    "color_palette": {
      "primary": [],
      "secondary": [],
      "background": []
    },
    "typography": []
  },
  "contact_info": {
    "emails": [],
    "phones": [],
    "social_links": {
      "facebook": "",
      "instagram": "",
      "twitter": "",
      "linkedin": "",
      "youtube": "",
      "tiktok": "",
      "whatsapp": ""
    },
    "physical_address": ""
  },
  "layout_and_nav": {
    "header_links": [],
    "footer_links": []
  },
  "content": {
    "h1_headings": [],
    "h2_headings": [],
    "call_to_action_buttons": [],
    "hero_image_url": "",
    "image_gallery": []
  },
  "assets": {
    "screenshot_file_path": ""
  }
}
```

**Extra fields** (extracted for `raw.md` only, not saved to `data.json`):

| Field | Source |
|---|---|
| `business_name` | `og:site_name` or `<title>` |
| `tagline` | `og:description` / meta description |
| `services` | Elements matching `[class*="service"]`, `.card`, `article`, etc. |
| `about` | `[class*="about"]` section or longest `<p>` |
| `testimonials` | `[class*="testimon"]`, `blockquote`, etc. |
| `raw_text_sections` | All `<section>`, `<article>`, `main > div` blocks |

---

## Extraction Details

### Metadata
- Page `<title>` and `og:title` (OG preferred)
- Meta `description` and `og:description`
- Favicon from `link[rel="icon"]`, `shortcut icon`, or `apple-touch-icon`
- `document.documentElement.lang`

### Branding — Color Palette
Three-pass extraction, deduplicated:
1. **CSS custom properties** (`--primary`, `--color-primary`, `--accent`, `--bg`, etc.)
2. **Computed background colors** of `body`, `main`, `section`, `footer` → background bucket
3. **Computed colors** of `header`, `nav`, buttons → primary; `h1`, `h2`, `a` → secondary

Near-black (`<5,5,5`) and near-white (`>248,248,248`) are discarded automatically. Up to 5 colors per bucket.

### Branding — Typography
`getComputedStyle().fontFamily` read from `body`, `h1`, `h2`, `h3`, `p`, `button`. First font family name only (no fallbacks).

### Contact — Phones
Regex on full `document.body.innerText`: matches `[+\d][\d\s\-(). ]{7,}` with ≥8 digit characters. Up to 3 results.

### Contact — Emails
Three-pass extraction for maximum coverage:
1. `a[href^="mailto:"]` links (most reliable)
2. Regex on visible body text
3. Regex on raw HTML (catches HTML-entity obfuscation: `&#64;`, `[at]`, etc.)

Up to 5 emails returned.

### Contact — Physical Address
Queries `address, [class*="address"], [itemprop="address"], [class*="contact"] address`.

Lines are split, trimmed, and filtered — **Italian VAT numbers (`P.IVA XXXXXXXXXX`) are stripped** before saving, since they commonly appear in the same `<address>` element.

```js
.filter(l => l && !/^P\.?\s*IVA\s+\d/i.test(l))
```

Result is `\n`-joined and capped at 200 characters.

### Contact — Social Links
All `a[href]` links on the page are matched against platform patterns:

| Platform | Pattern |
|---|---|
| Facebook | `facebook.com` |
| Instagram | `instagram.com` |
| Twitter/X | `twitter.com` or `x.com` |
| LinkedIn | `linkedin.com` |
| YouTube | `youtube.com` |
| TikTok | `tiktok.com` |
| WhatsApp | `whatsapp.com` or `wa.me` |

First match per platform wins.

### Layout — Navigation
- **Header links**: `nav a, header a` — label + href, deduplicated, up to 12
- **Footer links**: `footer a` — label + href, deduplicated, up to 12

Labels longer than 60 characters are excluded.

### Content — Headings & CTAs
- `h1`: up to 5, `h2`: up to 8
- CTAs: elements matching `.btn`, `[class*="btn"]`, `[class*="cta"]`, hero/banner links — up to 6

### Content — Images
- **Hero image**: `.hero img`, `header img`, or first element with a CSS `background-image`
- **Gallery**: all `<img>` with `naturalWidth > 200` and `naturalHeight > 150`, excluding anything with `logo` or `icon` in the URL — up to 8

---

## Cookie / GDPR Banner Dismissal

The scraper tries a prioritized list of selectors before extracting content:

```
button[id*='accept'], button[class*='accept'],
button[id*='cookie'], button[class*='cookie'],
a[id*='accept'], a[class*='accept'],
#cookieConsentButton, .cc-btn.cc-allow, .cc-accept,
[data-action='accept'], [aria-label*='accett'],
button:text('Accetta'), button:text('Accept'),
button:text('Accetto'), button:text('OK'),
button:text('Agree'), button:text('Allow')
```

On click, the scraper waits 800 ms and then continues. If none match (within 500 ms timeout), extraction proceeds anyway.

---

## Output Truncation in Logs

`scrape_site.py` prints the markdown summary to stdout, but only the first **15 lines**. The full summary is always available in `scrapes/<domain>/raw.md`.

```
─────────────────────────────────────────────────────────────
# Arte Ottica

**Source:** https://www.arte-ottica.com/

**Tagline:** ...

... (42 more lines truncated. see raw.md for full details)
```

---

## Architecture

```
create.sh  (step 6a)
    │
    ├── if WEBSITE_URL is set
    │       │
    │       ▼
    │   scripts/scrape_site.py <URL>
    │       │
    │       ├── Playwright → Chromium (headless)
    │       │     ├── page.goto()           load page
    │       │     ├── cookie banner dismiss
    │       │     ├── scroll (lazy content)
    │       │     ├── page.screenshot()
    │       │     └── page.evaluate() × 12  JS extraction passes
    │       │
    │       ├── scrapes/<domain>/data.json  ← structured schema
    │       ├── scrapes/<domain>/raw.md     ← AI-readable summary
    │       └── scrapes/<domain>/screenshot.png
    │
    └── raw.md injected into AI prompt as "REAL BUSINESS DATA"
            │
            ▼
        Claude / Gemini generates HTML using frontend-clone skill
```

---

## AI Usage Rules (injected with scraped data)

When `create.sh` injects `raw.md` into the prompt, it also injects these rules:

| Field | Rule |
|---|---|
| Business name, tagline, nav | Use from scraped data |
| Services | Use scraped services list (fall back to `raw_text_sections`) |
| About section | Use scraped about text |
| Contact info | Use scraped address, phone, email verbatim. Address **must** be wrapped in a Google Maps link |
| Social links | **Must** appear in Footer as Font Awesome icons. Use scraped URLs verbatim — never `#` placeholders |
| Brand colors | Base CSS palette on detected colors |
| Brand font | Use detected font or a harmonious companion via Google Fonts |
| Testimonials | Use scraped testimonials if any |
| Images | **Never hotlink** scraped image URLs — use local `assets/` files only |

---

## Dependencies

| Package | Purpose |
|---|---|
| `playwright` | Headless Chromium browser |
| `chromium` | Browser binary (`playwright install chromium`) |

Installation:

```bash
source venv/bin/activate
pip install playwright
playwright install chromium
```

---

## Known Limitations & Edge Cases

| Issue | Behaviour |
|---|---|
| Page load timeout (30 s) | Logs a warning, continues with partial content |
| Italian VAT numbers in `<address>` | Stripped server-side (`P.IVA XXXXXXXXXX` lines removed) |
| JS-rendered emails | Caught by HTML-entity pass (Pass 3) |
| Near-black / near-white colors | Filtered out of palette automatically |
| `scrapes/` directory | Not committed — regenerate by re-running the scraper |
| Images with `logo`/`icon` in URL | Excluded from gallery (but captured separately as `logo_url`) |
