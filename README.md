# Gemini Skills
<!-- Test update for git sync verification -->
 & Review Site Factory

A mono-repo that ships two tightly-coupled tools:

| Component | What it does |
|-----------|-------------|
| **Gemini CLI Extension** | Adds AI skills (image generation, frontend design) to the [Gemini CLI](https://github.com/google-gemini/gemini-cli) |
| **Review Site Factory** | FastAPI server that scrapes Google Maps with Playwright and auto-generates local-business landing pages using `create.sh` + Gemini CLI |

> **Why one repo?** `create.sh` (the site builder) directly calls the `nano-banana-pro` skill to generate images. Splitting would require publishing the skill as a separate package and adding a dependency layer. The coupling is intentional — keep them together until the skill is stable enough to version independently.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [System Dependencies (headless Playwright)](#2-system-dependencies-headless-playwright)
3. [Install uv (user-only, no sudo)](#3-install-uv-user-only-no-sudo)
4. [Python virtual environment & packages](#4-python-virtual-environment--packages)
5. [Install Playwright browsers](#5-install-playwright-browsers)
6. [Environment variables](#6-environment-variables)
7. [Install the Gemini CLI Extension](#7-install-the-gemini-cli-extension)
8. [Running the API server](#8-running-the-api-server)
9. [Testing](#9-testing)
10. [Repository structure](#10-repository-structure)
11. [Gemini CLI Skills reference](#11-gemini-cli-skills-reference)
12. [Extension management](#12-extension-management)

---

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.9.x | `python3 --version` (tested on 3.9.25) |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | latest | `gemini --version` |
| curl | any | for API tests |
| bc | any | for cost calculations in `create.sh` |

---

## 2. System Dependencies (headless Playwright)

Playwright's headless Chromium needs several native libraries. On **Fedora / RHEL / Rocky Linux**:

```bash
sudo dnf update -y
sudo dnf install -y \
    nss atk at-spi2-atk cups-libs libdrm mesa-libgbm \
    libXcomposite libXdamage libXext libXfixes libXrandr libxcb \
    libxkbcommon pango alsa-lib libXcursor libXi libXScrnSaver
```

On **Debian / Ubuntu**:

```bash
sudo apt-get update
sudo apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libgbm1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libxcb1 libxkbcommon0 libpango-1.0-0 \
    libasound2 libxcursor1 libxi6 libxss1
```

---

## 3. Install uv (user-only, no sudo)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager used by `create.sh` to run the image generation script. Install it **for your user only** (no root required):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then add it to your shell (add to `~/.bashrc` or `~/.zshrc` for persistence):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Verify:

```bash
uv --version
```

---

## 4. Python virtual environment & packages

```bash
# Clone the repo (or cd into it if already cloned)
git clone https://github.com/xoroz/gemini-skills.git
cd gemini-skills

# Create a virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

> **Tip:** Always activate the venv before running the API server or any test scripts.

---

## 5. Install Playwright browsers

After installing Python packages, install the Chromium browser binary that Playwright uses:

```bash
# Make sure the venv is active first
source venv/bin/activate

playwright install chromium
```

> This downloads a self-contained Chromium binary (~150 MB) into `~/.cache/ms-playwright/`.

### Verify Playwright works (headless smoke test)

```bash
python test-playwright.py
```

Expected output:

```
🚀 Starting Playwright test...
⏳ Launching headless Chromium...
🌐 Navigating to example.com...
✅ Success! Loaded page title: 'Example Domain'
📸 Taking a screenshot (test_shot.png)...
🏁 Test finished successfully.
```

A `test_shot.png` screenshot will be created in the project root.

---

## 6. Environment variables

Copy the example file and edit it:

```bash
cp .env.example .env
nano .env
```

Both `main.py` and `create.sh` automatically load `.env` on startup.
System environment variables always take precedence over the file.

### Required — at least one API key

```bash
# Primary image generation (Google AI Studio — free tier available)
export GEMINI_API_KEY="your-google-ai-studio-key"

# Fallback — uses google/gemini-2.5-flash-image via OpenRouter
export OPENROUTER_API_KEY="your-openrouter-key"
```

Get a free Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### `REMOTE_SITE_URL` — public site base URL ★

This is the most important setting for **remote / production deployments**.

The FastAPI server runs on one port (e.g. `:8080`) while nginx/apache
serves the generated HTML sites on a different URL (e.g. port 80).
`REMOTE_SITE_URL` tells the system where the sites are publicly accessible.

```bash
# .env  (or export in shell)
REMOTE_SITE_URL=http://192.168.0.114        # LAN — nginx on port 80
# REMOTE_SITE_URL=https://sites.example.com # Production domain
# REMOTE_SITE_URL=http://192.168.0.114/sites # If served under /sites/ prefix
```

**When `REMOTE_SITE_URL` is set:**

| Component | Effect |
|-----------|--------|
| `main.py` | `/generate-site` response immediately includes `site_url` |
| `create.sh` | Build summary prints the full `http://` URL |
| `test-all.py` | Remote mode validates the live site at `REMOTE_SITE_URL/<slug>/index.html` |

**Example `/generate-site` response with `REMOTE_SITE_URL` set:**

```json
{
  "status": "processing",
  "message": "Job added to queue.",
  "site_slug": "luigi-hair-salon",
  "site_url": "http://192.168.0.114/luigi-hair-salon/index.html"
}
```

**When `REMOTE_SITE_URL` is not set**, everything still works — only local
`file://` paths are shown in logs.

---

## 7. Configuration & Modes

The system supports two operation modes for `create.sh` (and the API) to balance cost vs. quality.

| Mode | Env Var | Image Model | Cost/Img | Use Case |
|------|---------|-------------|----------|----------|
| **PROD** (default) | `MODE=PROD` | `google/gemini-2.5-flash-image` | ~$0.038 | Final production builds |
| **DEV** | `MODE=DEV` | `black-forest-labs/flux.2-klein-4b` | ~$0.014 | Rapid testing & development |

### check_quota.sh

Since the Gemini CLI doesn't expose historical usage, use this script to perform a live health check (sends a minimal "Hello" prompt):

```bash
./check_quota.sh
# output: ✅ Gemini API is responding.
# or:     ❌ Gemini API failed. (QUOTA EXHAUSTED)
```

## 7. Install the Gemini CLI Extension

### From GitHub (recommended)

```bash
gemini extensions install https://github.com/xoroz/gemini-skills
```

### From a local path (for development)

```bash
gemini extensions link /path/to/gemini-skills
```

Changes to skill files are reflected immediately without reinstalling.

---

## 8. Running the API server

The FastAPI server exposes two endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/generate-site` | Queue a landing-page build job (async, calls `create.sh`) |
| `GET` | `/scrape-maps` | Scrape Google Maps listings with Playwright |

### Start the server

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Running `create.sh` directly (without the API)

```bash
# Italian (default) — Uses PROD mode (Gemini Flash images)
./create.sh "Officina Mario" "riparazione auto" "Via Roma 42, Milano" "+39 02 1234567"

# English + DEV mode (Cheap Flux images)
MODE=DEV SITE_LANG=en ./create.sh "Joe's Garage" "auto repair" "123 Main St" "555-1234"
```

Output is written to `sites/<business-slug>/` (ignored by `.gitignore`).

> **Pre-flight checks in `create.sh`:** The script verifies that `gemini` CLI is available and that at least one API key is set before doing any work.

---

## 9. Testing

### 9.1 Playwright headless smoke test

```bash
source venv/bin/activate
python test-playwright.py
```

### 9.2 Full End-to-End Integration Test

Runs the full pipeline: scrapes Google Maps, triggers a build, waits for
completion, and validates the result with Playwright.

```bash
source venv/bin/activate

# Local (default) — reads build.log and validates files on disk
python tests/test-all.py

# Custom search query
python tests/test-all.py --query "ristorante roma"

# Remote mode — API on :8080, sites served by nginx on :80
# (skips local file checks, validates the live HTTP URL instead)
python tests/test-all.py --remote --host 192.168.0.114 --port 8080

# Remote with explicit site root (if nginx serves under /sites/ prefix)
python tests/test-all.py --remote --host 192.168.0.114 --port 8080 \
    --remote-url http://192.168.0.114/sites
```

| CLI arg | Env var | Default | Description |
|---------|---------|---------|-------------|
| `--remote` | `REMOTE=true` | off | Skip local filesystem steps |
| `--host HOST` | — | localhost | Remote host IP or hostname |
| `--port PORT` | `PORT` | 8000 | FastAPI port |
| `--base-url URL` | `BASE_URL` | derived | Full FastAPI URL (overrides --host/--port) |
| `--remote-url URL` | `REMOTE_SITE_URL` | derived | Web server base serving the sites |
| `--query QUERY` | `QUERY` | parrucchiere la spezia | Maps search query |
| `--build-wait N` | `BUILD_WAIT` | 900 | Max seconds to wait for build |

**What each mode skips/runs:**

| Step | Local | Remote |
|------|-------|--------|
| Health check | ✅ | ✅ |
| Scrape Maps | ✅ | ✅ |
| Trigger build | ✅ | ✅ |
| Tail `build.log` | ✅ | ⏭ skipped |
| Check local files | ✅ | ⏭ skipped |
| Playwright `file://` | ✅ | ⏭ skipped |
| Poll `/status` API | ⏭ skipped | ✅ |
| Playwright `http://` | ⏭ skipped | ✅ |

### 9.3 API smoke tests (endpoints only)

Make sure the server is running first, then:

```bash
./tests/test-api.sh
```

Or against a remote server:

```bash
BASE_URL=http://your-server:8000 ./tests/test-api.sh
```

#### Manual curl examples

**Generate a site (async):**

```bash
curl -s -X POST "http://localhost:8000/generate-site" \
     -H "Content-Type: application/json" \
     -d '{
           "business_name": "Luigi Hair Salon",
           "niche": "parrucchiere",
           "address": "Via Roma 123, La Spezia, Italy",
           "tel": "+39 0187 123456",
           "webhook_url": "https://webhook.site/dummy-url-for-testing"
         }' | python3 -m json.tool
```

Expected response:

```json
{
    "status": "processing",
    "message": "Job added to queue."
}
```

**Scrape Google Maps:**

```bash
curl -s -X GET \
  "http://localhost:8000/scrape-maps?query=parrucchiere+la+spezia&max_results=3" \
  | python3 -m json.tool
```

Expected response shape:

```json
{
    "status": "success",
    "data": [
        {
            "business_name": "...",
            "niche": "parrucchiere",
            "address": "...",
            "tel": "...",
            "website": "..."
        }
    ]
}
```

---

## 10. Repository structure

```
gemini-skills/
│
├── gemini-extension.json     # Gemini CLI extension manifest
├── GEMINI.md                 # Context file auto-loaded by Gemini CLI
│
├── skills/                   # Gemini CLI skills
│   ├── nano-banana-pro/
│   │   ├── SKILL.md          # Skill instructions
│   │   └── scripts/
│   │       └── image.py      # Image generation script (uv-runnable)
│   └── frontend-design/
│       └── SKILL.md          # Frontend design skill instructions
│
├── main.py                   # FastAPI server (Review Site Factory API)
├── create.sh                 # Landing page builder (calls Gemini CLI + image.py)
├── requirements.txt          # Python dependencies for the API server
│
├── test-playwright.py        # Headless Playwright smoke test
├── tests/
│   └── test-api.sh           # API endpoint smoke tests
│
├── sites/                    # Generated sites output (git-ignored)
│   └── <business-slug>/
│       ├── index.html
│       ├── style.css
│       ├── build.log
│       └── assets/           # AI-generated images
│
├── .gitignore
├── LICENSE
└── README.md
```

---

## 11. Troubleshooting

### Quota Exhausted / Rate Limits

If the Gemini API returns `MODEL_CAPACITY_EXHAUSTED` (429), the `create.sh` script automatically:

1. **Pauses** for 60 seconds (exponential backoff: 60s, 120s, 180s).
2. **Retries** the generation up to 3 times.
3. **Resumes** automatically if quota frees up.

Check live availability with `./check_quota.sh`.

### Syntax Errors in create.sh

If you see `syntax error near unexpected token`, ensure you're using `bash` 4.0+ and not `sh`. The script uses arrays and process substitution.

---

## 11. Gemini CLI Skills reference

### Nano Banana Pro — Image Generation

Generates images using Google's Gemini 2.5 Flash model.

**Triggers:** `generate image`, `create image`, `make image`, `nano banana`, `image-generation`

**Direct script usage:**

```bash
uv run skills/nano-banana-pro/scripts/image.py \
  --prompt "A dramatic hero photo for a hair salon in La Spezia" \
  --output "/tmp/hero.png" \
  --aspect landscape \   # square | landscape | portrait
  --quality draft \      # high | draft
  --provider auto        # auto | gemini | openrouter
```

### Frontend Design

Creates distinctive, production-grade frontend interfaces.

**Triggers:** `frontend`, `design`, `ui`, `web`, `component`, `page`, `interface`, `landing page`, `dashboard`, `website`

---

## 12. Extension management

```bash
# List installed extensions
gemini extensions list

# Update this extension
gemini extensions update buildatscale-gemini-skills

# Disable / enable
gemini extensions disable buildatscale-gemini-skills
gemini extensions enable buildatscale-gemini-skills

# Uninstall
gemini extensions uninstall buildatscale-gemini-skills
```

---

## License

MIT
