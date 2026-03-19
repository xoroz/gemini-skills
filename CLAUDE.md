# gemini-skills — AI Backend

## What this repo is

A mono-repo with two tightly-coupled components:

| Component | What it does |
|-----------|--------------|
| **Gemini CLI Extension** | Adds AI skills (image generation, frontend design) to Gemini CLI |
| **Review Site Factory** | FastAPI server that auto-generates landing pages, A5 print flyers with QR codes, and sends email summaries via SMTP |

`create.sh` calls the `nano-banana-pro` skill directly — the coupling is intentional.

---

# GLobal Project Understanding and view

Requirement to have MCP to notion working and
his file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Project Task Manager — Notion Integration

## Identity

You are a developer working on the Texngo project ecosystem.
You have access to Notion via MCP to manage tasks.

## Notion References

- **Task Board (database):** `30bd1cb0-80ca-8082-bec9-f98264a81588`
- **Data Source (collection):** `collection://310d1cb0-80ca-80bd-adfa-000b08ba1779`
- **Project Wiki:** `31ed1cb0-80ca-8113-a2c9-e0db4933342b`
- **Wiki Pages:**
  - 🔵 texngo: `31ed1cb0-80ca-8160-a785-e1b36ced5261`
  - 🟡 texngo-ai: `31ed1cb0-80ca-81b8-8d03-cc579c340435`
  - 🟤 autosite: `31ed1cb0-80ca-81ba-ad4d-e22c6b30d659`

## Project Detection

Detect the current project from the repo folder name:

- If folder contains `texngo-ai` → Project = **texngo-ai**
- If folder contains `gemini-skills` → Project = **autosite**
- If folder contains `texngo` (but not `texngo-ai`) → Project = **texngo**
- Otherwise → ask the user which project this repo belongs to

## Task Workflow

### When starting a session or when asked to "pick a task"

1. **Detect project** from the current working directory
2. **Fetch the project wiki page** (using the wiki page ID above) to understand the project context, tech stack, and architecture
3. **Search the task board** for tasks where:
   - `Project` = detected project name
   - `Status` = "Not started"
4. **List the tasks** with numbers and ask the user which one to work on
5. **When user picks a task:**
   a. Fetch the full task page to read any description/notes
   b. Update the task Status to **"In progress"** using:

      ```
      notion-update-page → command: "update_properties"
      page_id: <task_page_id>
      properties: { "Status": "In progress" }
      ```

   c. Begin working on the task in the codebase
6. **When the task is complete:**
   a. Update the task Status to **"Done"** using:

      ```
      notion-update-page → command: "update_properties"
      page_id: <task_page_id>
      properties: { "Status": "Done" }
      ```

   b. Optionally add a summary of what was done to the task page content

## Task Board Schema

The Notion database has these properties:

- **Name** (title) — task name
- **Status** (status) — "Not started" | "In progress" | "Done"
- **Project** (select) — "texngo" | "texngo-ai" | "autosite"
- **Assign** (person) — who is assigned

## Rules

- Always fetch the wiki page FIRST to understand project context before coding
- Never skip updating status — move to "In progress" before starting work
- When done, always move to "Done" and briefly note what was changed
- If a task is unclear, read the task page content for details
- If still unclear, ask the user before proceeding!

---

## Stack

- **Python + FastAPI** (`main.py`)
- Runs as a **systemd service** (`gemini-skills`)
- Python **venv** required (`source venv/bin/activate`)
- **Python 3.11** required (prod). Local system default is 3.9 — always create venv with `python3.11 -m venv venv`
  - Install 3.11 on RHEL 9: `sudo dnf install python3.11 python3.11-devel -y`
  - Use `typing.Optional`/`typing.List` (not `X | None` or `list[X]`) so code runs on both 3.9 and 3.11
  - If Nexus proxy (nexus-pro) returns 502, fall back to PyPI: `venv/bin/pip install -r requirements.txt --index-url https://pypi.org/simple/`
- `uv` used by scripts (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

---

## Setup

```bash
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## Service management

```bash
sudo systemctl status gemini-skills
sudo systemctl restart gemini-skills    # after any code changes
journalctl -u gemini-skills -f          # live logs
tail -f logs/backend.log                # streamed build output
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | public | System check |
| POST | `/generate-site` | Bearer | Queue a landing-page build |
| GET | `/scrape-maps` | Bearer | Scrape Google Maps listings |
| GET | `/build-log/{slug}` | Bearer | Poll build logs and stats |
| POST | `/modify-site` | Bearer | Modify an existing site |

Docs: `http://localhost:8000/docs`

---

## Key Scripts

| Script | Purpose |
|--------|---------|
| `create.sh` | Landing page builder — calls Gemini CLI + image.py |
| `creator/CLAUDE.md` | Focused system prompt for site generation AI (injected via `-p`) |
| `creator/skills/` | Symlinks to `frontend-design` and `frontend-clone` skills |
| `scripts/make_flyer.py` | Stamps QR code + ID onto A5 template, outputs TIFF (CMYK) + PNG |
| `scripts/id_manager.py` | CRUD for `sites/site-id.json` (allocate / assign / lookup / unassign / update / list) |
| `assets/bin/send_mail.py` | General SMTP mailer |
| `check_quota.sh` | Live Gemini API health check |

---

## Modes

| Mode | Env Var | Image Model | Cost/Img |
|------|---------|-------------|----------|
| **PROD** (default) | `MODE=PROD` | `google/gemini-2.5-flash-image` | ~$0.038 |
| **DEV** | `MODE=DEV` | `black-forest-labs/flux.2-klein-4b` | ~$0.014 |

DEV/MOCKUP mode uses `sites/site-id-dev.json` (registry isolation).

---

## Key Environment Variables

```bash
GEMINI_API_KEY=           # Primary image generation
OPENROUTER_API_KEY=       # Fallback image generation
REMOTE_SITE_URL=          # Public base URL for generated sites
API_TOKEN=                # Bearer token to protect endpoints
ALLOWED_ORIGINS=          # Comma-separated CORS origins
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS   # Email notifications
```

---

## Flyer System (FlyerSystem.md)

Short ID format: `NNL` (e.g. `00A`) — 2600 total IDs.

**Pre-print workflow:**

```bash
# 1. Batch generate print-ready TIFFs
uv run scripts/make_flyer.py --site-id "00A-00J" --force --remote-url "https://texngo.it" --format tiff

# 2. Client claims flyer 00B → build site
SITE_ID=00B ./create.sh "Business" "niche" "address" "tel"

# 3. Update registry URL
uv run scripts/id_manager.py update --id 00B --remote-url "https://texngo.it"

# 4. Regen flyer with updated QR
uv run scripts/make_flyer.py --site-id 00B --format both
```

Print spec: A5, 300 DPI, CMYK, FOGRA39L ICC, 1819×2551 px.

---

## Skills

This repo provides two AI skills used by `create.sh`:

### Nano Banana Pro (Image Generation)

Generate images using OpenRouter or Google GenAI.

```bash
uv run skills/nano-banana-pro/scripts/image.py \
  --prompt "Your image description" \
  --output "/path/to/output.png" \
  --aspect landscape \
  --quality draft \
  --web  # auto-convert to optimized WebP
```

### Frontend Design

Skill instructions for generating landing pages. See `skills/frontend-design/SKILL.md` for the full design blueprint used when generating HTML/CSS.

### Text Engine

`create.sh` supports two text generation engines:

```bash
# Default: Claude (sonnet)
./create.sh "Business" "niche" "address" "contact"

# Use Gemini instead
TEXT_ENGINE=gemini ./create.sh "Business" "niche" "address" "contact"

# Override model
TEXT_ENGINE=claude AI_MODEL_TEXT=opus ./create.sh ...
TEXT_ENGINE=gemini AI_MODEL_TEXT=gemini-3-flash-preview ./create.sh ...
```

### Gemini CLI Extension

| Skill | Triggers |
|-------|---------|
| **nano-banana-pro** | "generate image", "create image", "nano banana" |
| **frontend-design** | "frontend", "design", "ui", "landing page", "dashboard" |

Install extension:

```bash
gemini extensions install https://github.com/xoroz/gemini-skills
# or for local dev:
gemini extensions link /path/to/gemini-skills
```

---

## Agent Rules (.agent/rules/AGENTS.md)

- No `sudo`
- Never read/output `.env` or secrets
- Zero-cost tests only unless user approves paid API calls
- Commit format: conventional commits (`feat:`, `fix:`, `chore:`)

---

## Local testing

```bash
source venv/bin/activate

# Smoke tests
python test-playwright.py
./tests/test-api.sh

# Full E2E
python tests/test-all.py
python tests/test-all.py --remote --host 192.168.0.114 --port 8080
```

---

## Rules

- Always activate venv first
- Restart systemd service after any code changes
- Never commit `.env`, `venv/`, `__pycache__/`, `*.pyc`, `sites/`
- If changing API contract, update `texngo-ai` `.env` endpoint too
- Deploy takes ~30 min — test locally first
- Test with `./check_quota.sh` before any paid API calls
