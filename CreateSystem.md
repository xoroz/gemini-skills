# Create System

Complete reference for `create.sh` — the main landing page builder that orchestrates scraping, AI image generation, HTML/CSS generation, ID allocation, flyer creation, and email notification.

---

## Usage

```bash
./create.sh [--website <url>] "Business Name" "Niche" "Address" "Contact Info"
```

### Positional arguments

| # | Argument | Example |
|---|---|---|
| 1 | Business Name | `"Officina Mario"` |
| 2 | Niche | `"riparazione auto"` |
| 3 | Address | `"Via Roma 42, Milano"` |
| 4 | Contact Info | `"+39 02 1234567"` |

### Optional flags

| Flag / Env Var | Description |
|---|---|
| `--website <url>` | Scrape a source URL and clone the site with real data |
| `WEBSITE_URL=<url>` | Same as `--website` (for FastAPI / programmatic use) |
| `SITE_LANG=en` | Output language: `it` (default) or `en` |
| `MODE=<mode>` | Quality/cost mode (see below) |
| `TEXT_ENGINE=gemini` | Use Gemini CLI instead of Claude for text |
| `SITE_ID=00B` | Pre-assign a specific short ID (otherwise auto-allocated) |

---

## Modes

| Mode | Image Model | Img Cost | Prompt Gen Model | Text Model (Claude) | Text Model (Gemini) |
|------|-------------|----------|------------------|---------------------|---------------------|
| **DEV** (default) | `flux.2-klein-4b` | ~$0.014 | `gemini-2.0-flash-lite` | `sonnet` | `gemini-2.5-flash` |
| **PROD** | `gemini-2.5-flash-image` | ~$0.038 | `gemini-2.5-flash` | `sonnet` | `gemini-3-flash-preview` |
| **SUPER** | `gemini-3.1-flash-image-preview` | ~$0.068 | `gemini-2.5-pro` | `sonnet` | `gemini-3.1-pro-preview` |
| **MOCKUP** | local `dummy.png` (no API) | $0.00 | skipped | `sonnet` | `gemini-2.5-flash-lite` |

All models can be overridden via `.env` or environment:

```bash
AI_MODEL_IMG=google/gemini-2.5-flash-image   # image generation model
AI_MODEL_TEXT=claude-opus-4                   # text generation model
AI_COST_IMG=0.038                             # cost per image (for stats)
```

`SUPER` note: only `gemini-3.1-flash-image-preview` supports 0.5K resolution.

---

## Quick Examples

```bash
# Standard build (DEV mode, Italian)
./create.sh "Officina Mario" "riparazione auto" "Via Roma 42, Milano" "+39 02 1234567"

# English landing page
SITE_LANG=en ./create.sh "Joe's Garage" "auto repair" "123 Main St" "555-1234"

# Production quality
MODE=PROD ./create.sh "Ristorante Bella" "ristorante" "Via Po 1, Roma" "+39 06 9999"

# Highest quality
MODE=SUPER ./create.sh "Hotel Lusso" "luxury hotel" "Piazza Navona 1" "+39 06 1111"

# Clone an existing website (frontend-clone mode)
./create.sh --website https://client-site.it "Agenzia Viaggi" "turismo" "Via Roma 1" "+39 0585 123"

# Pre-assign a flyer short ID
SITE_ID=00B MODE=PROD ./create.sh "Marble Nails" "nail art" "Via Roma 1, La Spezia" "+39 0187 123456"

# Use Gemini for text instead of Claude
TEXT_ENGINE=gemini ./create.sh "Test Business" "niche" "address" "contact"

# Mockup — no image API calls, fastest build
MODE=MOCKUP ./create.sh "Preview Test" "test" "Via Test 1" "+39 000"
```

---

## Step-by-Step Execution Flow

```
  ┌───────────────────────────────────────────────────────────────┐
  │  0. Env & path setup                                          │
  │     → PATH extended: ~/.local/bin, ~/.cargo/bin, NVM          │
  │     → .env loaded (system env vars always win)                │
  │     → IMAGE_SCRIPT, MAIL_SCRIPT, ID_MANAGER paths set         │
  ├───────────────────────────────────────────────────────────────┤
  │  1. Parse inputs & validate                                   │
  │     → --website flag or WEBSITE_URL parsed                    │
  │     → BUSINESS_NAME, NICHE, ADDRESS, CONTACT validated        │
  │     → GEMINI_API_KEY or OPENROUTER_API_KEY required           │
  ├───────────────────────────────────────────────────────────────┤
  │  2. Language configuration                                    │
  │     → SITE_LANG=it (default) or en                           │
  │     → Sets LANG_INSTRUCTION and SECTION_NAMES for prompts     │
  ├───────────────────────────────────────────────────────────────┤
  │  3. Create folder structure                                   │
  │     → sites/<slug>/          (site output folder)             │
  │     → sites/<slug>/assets/   (images land here)              │
  │     → sites/<slug>/build.log (per-build log)                 │
  │     → logs/backend.log       (global stream log)             │
  │     → Existing folder renamed to <slug>_old                  │
  ├───────────────────────────────────────────────────────────────┤
  │  4. Track stats                                               │
  │     → START_TIME captured for elapsed time calc              │
  │     → Image counters initialised                             │
  ├───────────────────────────────────────────────────────────────┤
  │  4b. Scrape source website (clone mode only)                  │
  │      → Runs scripts/scrape_site.py on WEBSITE_URL            │
  │      → Outputs: scrapes/<domain>/data.json + raw.md          │
  │      → Sets SCRAPED_DATA, SCRAPE_SKILL_SECTION, SCRAPE_DOMAIN │
  │      → Dismisses cookie banners, scrolls, screenshots page   │
  │      ⚠ Must run BEFORE image generation (step 5)             │
  ├───────────────────────────────────────────────────────────────┤
  │  5. Generate images (Nano Banana Pro)                        │
  │     → 6 images: hero, gallery-1, gallery-2,                  │
  │                 workshop, detail, process                     │
  │     → Default prompts use $BUSINESS_NAME + $NICHE            │
  │     → Model + cost set by MODE (see table above)             │
  │     → MOCKUP: copies local dummy.png, no API call            │
  │     → Retry logic: 2 retries, exponential backoff            │
  │     → Rate limit detection (per-minute vs daily quota)       │
  │     → 3s delay between images (PROD/SUPER, not DEV)          │
  ├───────────────────────────────────────────────────────────────┤
  │  5a. Smart image prompts (clone mode only)                    │
  │      → Calls scripts/generate_image_prompts.py               │
  │      → Reads data.json + raw.md from scrape step             │
  │      → Calls Gemini API (primary) → OpenRouter (fallback)    │
  │      → Model tier matches MODE (flash-lite / flash / pro)    │
  │      → Overrides IMAGES[] array with business-specific text  │
  │      → Gracefully falls back to generic prompts on failure   │
  │      → MOCKUP: skipped entirely                              │
  ├───────────────────────────────────────────────────────────────┤
  │  5b. Optimize images (PNG → WebP)                            │
  │      → scripts/optimize_images.py                            │
  │      → Max 1200×900, quality 82, replaces originals          │
  │      → Skipped in MOCKUP mode                                │
  ├───────────────────────────────────────────────────────────────┤
  │  6. Generate HTML (index.html)                               │
  │     → Uses SCRAPED_DATA (if clone) or business details only  │
  │     → Prompt includes: skill, language rules, sections,      │
  │       image asset paths, design requirements, JS rules       │
  │     → Text engine: Claude (default) or Gemini CLI            │
  │     → Output post-processed:                                 │
  │       - AI preamble stripped (keeps from <!DOCTYPE)          │
  │       - integrity/crossorigin attrs removed                  │
  │       - Repeated-char patterns removed                       │
  │       - HTML structure validated (<html> + </html> required) │
  ├───────────────────────────────────────────────────────────────┤
  │  7. Generate CSS (style.css)                                  │
  │     → Full HTML fed back into prompt for class-name matching  │
  │     → Same text engine and retry logic as HTML               │
  │     → AI preamble stripped (keeps from @/:/comment)          │
  ├───────────────────────────────────────────────────────────────┤
  │  8. Allocate short ID                                        │
  │     → scripts/id_manager.py allocate (auto) or assign (manual│
  │     → Creates sites/<ID>.html — iframe wrapper with CTA bar  │
  │     → Claim bar: 48h reservation message + texngo.it link    │
  │     → Language-aware copy (Italian / English)               │
  ├───────────────────────────────────────────────────────────────┤
  │  9. Stats, URL check, email notification                     │
  │     → Elapsed time, image counts, cost breakdown             │
  │     → Remote URL tested with curl -f                         │
  │     → Site zipped and emailed via assets/bin/send_mail.py    │
  └───────────────────────────────────────────────────────────────┘
```

---

## Output Structure

```
sites/
├── <slug>/
│   ├── assets/
│   │   ├── hero.webp
│   │   ├── gallery-1.webp
│   │   ├── gallery-2.webp
│   │   ├── workshop.webp
│   │   ├── detail.webp
│   │   └── process.webp
│   ├── index.html
│   ├── style.css
│   └── build.log          ← per-build log
├── <ID>.html               ← short-ID redirect wrapper (e.g. 00A.html)
└── _failed/               ← failed builds moved here automatically
```

---

## Image Generation (Step 5)

Six images are generated with `skills/nano-banana-pro/scripts/image.py`:

| Asset | Default prompt theme |
|-------|---------------------|
| `hero` | Cinematic wide-angle shot of the business |
| `gallery-1` | Studio product/service photograph |
| `gallery-2` | Alternative angle, catalog style |
| `workshop` | Wide interior / workspace shot |
| `detail` | Macro of craftsmanship / materials |
| `process` | Action candid of workflow in motion |

In **clone mode**, these defaults are replaced by AI-generated prompts tailored to the scraped business data (step 5a).

### Model selection by MODE

| MODE | Image Model | Via |
|------|-------------|-----|
| DEV | `black-forest-labs/flux.2-klein-4b` | OpenRouter |
| PROD | `google/gemini-2.5-flash-image` | OpenRouter / Gemini |
| SUPER | `google/gemini-3.1-flash-image-preview` | OpenRouter / Gemini |
| MOCKUP | `local .skel/dummy.png` | No API |

Override: `AI_MODEL_IMG=<model>` in `.env`.

### Rate limit handling

- **Per-minute 429**: exponential backoff (30s, 60s), up to 2 retries
- **Daily quota**: aborts immediately, marks all remaining images as failed
- **Delay between images**: 3s in PROD/SUPER (skipped in DEV — cheap model has no concerns)
- **Failure threshold**: any failed image aborts the build (`exit 1`)

---

## Smart Image Prompts (Step 5a — clone mode only)

When `WEBSITE_URL` is set and scraping succeeds, `scripts/generate_image_prompts.py` is called to replace the generic prompts with business-specific ones.

### How it works

1. Reads `scrapes/<domain>/data.json` (brand colors, fonts, H1/H2, services)
2. Reads `scrapes/<domain>/raw.md` (first 1500 chars as AI context)
3. Calls text model to generate 6 JSON image prompts
4. Outputs shell-sourceable `SMART_IMG_*` variables
5. `create.sh` sources the file and overrides the `IMAGES[]` array

### Model selection by MODE

| MODE | Prompt Gen Model |
|------|-----------------|
| DEV | `gemini-2.0-flash-lite` |
| PROD | `gemini-2.5-flash` |
| SUPER | `gemini-2.5-pro` |
| MOCKUP | skipped |

Primary: Gemini REST API (`GEMINI_API_KEY`).
Fallback: OpenRouter (`OPENROUTER_API_KEY`) with `openai/gpt-4o-mini`.
If both fail: generic prompts used silently (non-fatal).

---

## Text Generation (Steps 6 & 7)

HTML and CSS are generated via the `generate_text_with_retry()` function.

### Engines

| `TEXT_ENGINE` | CLI Used | Default Model |
|---|---|---|
| `claude` (default) | `claude -p --model <model> --dangerously-skip-permissions --tools ""` | `sonnet` |
| `gemini` | `gemini -m <model> -y -p ""` | varies by MODE |

Override model: `AI_MODEL_TEXT=<model>` or `AI_MODEL_TEXT=opus` etc.

### Retry logic

| Attempt | Engine | Action |
|---------|--------|--------|
| 1 | Primary (`TEXT_ENGINE`) | Try normally |
| 2 | Primary | Retry after backoff (30s for rate limits, 10s for other errors) |
| 3 | **Other engine** (fallback) | Switches to Claude↔Gemini automatically |

Failure conditions that trigger retry:
- Exit code ≠ 0
- Empty output file
- `"hit your limit"` / `"usage limit"` messages in content
- Missing `</html>` (HTML truncated — model hit output token cap)

### HTML post-processing

After generation, `index.html` is cleaned:
1. **Preamble strip**: keeps from `<!DOCTYPE`, `<html`, or ` ```html` block
2. **Integrity attrs**: `integrity="..."` and `crossorigin="..."` removed (AI hallucinates bogus SHA hashes)
3. **Runaway patterns**: single char repeated 100+ times removed
4. **Validation**: must contain both `<html` and `</html>` or build aborts

### CSS post-processing

The full `index.html` is fed back into the CSS prompt so the AI can match exact class names. AI preamble is stripped (CSS must start with `@`, `:`, `/`, `.`, `#`, or a letter).

---

## Language Support

| `SITE_LANG` | Language | Section names |
|---|---|---|
| `it` (default) | Italian | Navigazione, Hero, Servizi, Galleria, Chi Siamo, Processo, Testimonianze, Contatti, Footer |
| `en` | English | Header/Nav, Hero, Services, Recent Work, About, Process, Testimonials, Contact, Footer |

Unknown values fall back to `it` with a warning.

---

## Short ID & Redirect Page (Step 8)

After the site is built, `id_manager.py` assigns a short `NNL` ID (e.g. `00B`).

`sites/<ID>.html` is generated as a **full-page iframe wrapper** with a "Claim Your Site" banner:

```
┌───────────────────────────────────────────────────────────┐
│ ⏳ This AI-generated site... is reserved for 48 hours.   │
│                                         [🚀 Claim Site]   │
├───────────────────────────────────────────────────────────┤
│                                                           │
│              <iframe src="slug/index.html">               │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

- The claim button pre-fills a contact form on texngo.it with the business name
- The actual site files are **never modified** by the wrapper
- Language-aware: Italian or English copy depending on `SITE_LANG`

---

## Error Handling

| Error | Action |
|---|---|
| Missing `BUSINESS_NAME` or `NICHE` | Print usage, `exit 1` |
| No API key | Print error, `exit 1` |
| Any image fails | `exit 1` (halts build) |
| HTML/CSS generation fails after all retries | `exit 1` |
| Scrape fails | Warning only — build continues without scraped data |
| Smart prompt generation fails | Warning only — generic prompts used |
| HTML truncated (no `</html>`) | Triggers retry |
| Script exits with any error | `trap on_error EXIT` fires |

On fatal error:
1. Failed site folder moved to `sites/_failed/<slug>/`
2. Build summary email sent with `status=FAILED`

---

## Logging

All output is tee'd to three destinations simultaneously:

| Destination | How to read |
|---|---|
| stdout | captured by FastAPI (`main.py`) via subprocess pipe |
| `sites/<slug>/build.log` | per-build log, attached to email |
| `logs/backend.log` | global stream: `tail -f logs/backend.log` |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MODE` | `DEV` | Quality/cost tier |
| `SITE_LANG` | `it` | Output language |
| `TEXT_ENGINE` | `claude` | `claude` or `gemini` |
| `WEBSITE_URL` | — | URL to scrape (clone mode) |
| `SITE_ID` | — | Pre-assign a specific short ID |
| `REMOTE_SITE_URL` | — | Public base URL (e.g. `https://texngo.it`) |
| `GEMINI_API_KEY` | — | Required (or `OPENROUTER_API_KEY`) |
| `OPENROUTER_API_KEY` | — | Required (or `GEMINI_API_KEY`) |
| `AI_MODEL_IMG` | mode default | Override image model |
| `AI_MODEL_TEXT` | mode default | Override text model |
| `AI_COST_IMG` | mode default | Override cost per image (stats only) |
| `SMTP_HOST/PORT/USER/PASS` | — | Email notification config |

---

## Key Files

| File | Role |
|---|---|
| `create.sh` | Main orchestrator |
| `scripts/scrape_site.py` | Playwright scraper (step 4b) |
| `scripts/generate_image_prompts.py` | AI prompt generator (step 5a) |
| `skills/nano-banana-pro/scripts/image.py` | Image generation via AI |
| `scripts/optimize_images.py` | PNG → WebP converter |
| `scripts/id_manager.py` | Short ID registry CRUD |
| `assets/bin/send_mail.py` | SMTP email sender |
| `.skel/` | Skeleton: `dummy.png`, folder template |
| `sites/` | All generated site output |
| `scrapes/` | Cached scrape data (not committed) |
| `logs/backend.log` | Global build log stream |

---

## Cost Breakdown (per site)

| Item | DEV | PROD | SUPER | MOCKUP |
|------|-----|------|-------|--------|
| 6 images | ~$0.08 | ~$0.23 | ~$0.41 | $0.00 |
| Smart prompts (clone) | ~$0.00 | ~$0.00 | ~$0.01 | skipped |
| HTML + CSS (text) | ~$0.01 | ~$0.01 | ~$0.01 | ~$0.01 |
| **Total** | **~$0.09** | **~$0.24** | **~$0.42** | **~$0.01** |

Image costs only apply when using OpenRouter. Gemini native API images are billed to the Google AI plan separately.

---

## Triggering via FastAPI

`create.sh` is called by `main.py` (`POST /generate-site`) with all arguments as environment variables piped as a subprocess:

```python
process = subprocess.Popen(
    ["./create.sh", business, niche, address, contact],
    env={**os.environ, "MODE": mode, "WEBSITE_URL": website_url, ...},
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
```

Build logs stream to `logs/backend.log` and are polled via `GET /build-log/<slug>`.

---

## Creator System (`creator/`)

The `creator/` directory provides a focused AI context for site generation, replacing the noisy root `CLAUDE.md` during HTML/CSS generation.

```
creator/
├── CLAUDE.md        ← focused system prompt injected via -p flag
└── skills/
    ├── frontend-design  → symlink: ../../skills/frontend-design
    └── frontend-clone   → symlink: ../../skills/frontend-clone
```

### How it works

`create.sh` loads `creator/CLAUDE.md` at startup into `$CREATOR_PREAMBLE` and passes it as the `-p` argument to `claude`. This means Claude receives the full design rules as its system prompt instead of the brief one-liner that was previously hardcoded.

`CLAUDE_CODE_SIMPLE=1` stays in place to prevent the root `CLAUDE.md` (which contains Notion, FastAPI, and systemd content) from loading during site generation.

### Updating AI behavior

To change how Claude generates sites, edit `creator/CLAUDE.md`. No changes to `create.sh` are needed. The file is loaded fresh on every `create.sh` run.

### Fallback

If `creator/CLAUDE.md` is missing, `create.sh` falls back to a short hardcoded preamble so builds never break silently.
