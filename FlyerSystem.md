# TexNGo Flyer System

Complete reference for the flyer generation pipeline, ID registry, and the `id_manager.py` CLI tool.

---

## Workflow: Pre-Creation (Print Before Sites Exist)

The typical use-case: **pre-print 10–50 flyers** with unique QR codes, hand them out,
then build sites later when a client claims their flyer.

### Step 1 — Batch-generate flyers with `--force`

```bash
# Generate 10 print-ready TIFF flyers (00A → 00J)
# --force auto-registers placeholder entries in site-id.json
uv run scripts/make_flyer.py \
  --site-id "00A-00J" \
  --force \
  --remote-url "https://texngo.it" \
  --format tiff
```

This creates:

- **10 TIFF files** in `assets/flyers/` (CMYK, 300 DPI, FOGRA39L)
- **10 placeholder entries** in `sites/site-id.json` with QR URLs like `https://texngo.it/00B.html`

Each flyer has a unique QR code pointing to `https://texngo.it/<ID>.html` and a tiny `ID: 00B` stamp at the bottom-left.

### Step 2 — Hand out flyers

Print the TIFFs and distribute. Each flyer's QR code leads to a unique URL.

### Step 3 — Client claims a flyer → build their site

When a client with flyer `00B` wants their site:

```bash
# Build the site (creates the HTML/CSS/images + allocates the slug)
SITE_ID=00B ./create.sh "Marble Nails di Bertola Giada" "nail art" "Via Roma 1, La Spezia" "+39 0187 123456"
```

`create.sh` will see `SITE_ID=00B` and assign that ID to the new site.

### Step 4 — Update the registry with real URLs

```bash
# Point 00B to the production server
uv run scripts/id_manager.py update \
  --id 00B \
  --remote-url "https://texngo.it"
```

### Step 5 — Regenerate the redirect page

The `create.sh` script already creates `sites/00B.html` (iframe wrapper with Claim CTA).
If you need to regenerate just the flyer with the updated URL:

```bash
uv run scripts/make_flyer.py --site-id 00B --format both
```

### Full lifecycle summary

```
  ┌─────────────────────────────────────────────────────────┐
  │ 1. Pre-print:  --force --site-id 00A-00J                │
  │    → TIFF flyers ready, QR → texngo.it/00X.html         │
  │    → Placeholder entries in site-id.json                │
  ├─────────────────────────────────────────────────────────┤
  │ 2. Hand out flyers to potential clients                  │
  ├─────────────────────────────────────────────────────────┤
  │ 3. Client claims flyer 00B → build site:                │
  │    SITE_ID=00B ./create.sh "Business" "niche" ...       │
  │    → site built, ID assigned, redirect page created     │
  ├─────────────────────────────────────────────────────────┤
  │ 4. Update URL:  id_manager.py update --id 00B ...       │
  │ 5. Regen flyer: make_flyer.py --site-id 00B --format .. │
  └─────────────────────────────────────────────────────────┘
```

### Batch examples

```bash
# 10 flyers pre-printed:
uv run scripts/make_flyer.py --site-id "00A-00J" --force --remote-url "https://texngo.it" --format tiff

# Range + individual:
uv run scripts/make_flyer.py --site-id "00A-00E,01A" --force --remote-url "https://texngo.it"

# Re-generate for existing registry entries (no --force needed):
uv run scripts/make_flyer.py --site-id "00A-00E" --format both

# Single flyer with explicit name/URL:
uv run scripts/make_flyer.py --name "My Business" --url "https://texngo.it/00A.html" --site-id 00A

# Uncoated paper:
uv run scripts/make_flyer.py --site-id "00A-00J" --force --remote-url "https://texngo.it" --paper uncoated
```

---

## Architecture Overview

```
sites/site-id.json          ← registry (ID ↔ slug ↔ URL mapping)
        ↓  read/write
scripts/id_manager.py       ← CLI: allocate / assign / lookup / unassign / update
        ↓  called by
create.sh  (step 9)         ← auto-runs make_flyer.py every build
        ↓
scripts/make_flyer.py       ← opens template, generates QR, pastes it, stamps ID
        ↓
assets/flyers/flyer-<ID>.tiff           ← CMYK print-ready (FOGRA39L, 300 DPI)
assets/flyers/flyer-<ID>.png            ← RGB preview
sites/<slug>/assets/flyer-<ID>.png      ← PNG copy lives with the site
```

**Cost: $0.00** — no AI calls, purely local Pillow + qrcode rendering.

---

## Files

| File | Purpose |
|---|---|
| `assets/template-flyer.png` | Branded A5 source template (1080×1350 px). |
| `assets/template-flyer-300dpi.png` | Upscaled print-ready template (1819×2551 px, 300 DPI). |
| `assets/icc/FOGRA39L_coated.icc` | ICC profile for coated paper (bundled, no system dependency). |
| `assets/icc/FOGRA47L_uncoated.icc` | ICC profile for uncoated paper. |
| `scripts/make_flyer.py` | Stamps QR code + ID onto template. Supports batch + force mode. |
| `scripts/upscale_template.py` | One-shot utility to upscale template to 300 DPI. |
| `scripts/id_manager.py` | CRUD for `sites/site-id.json`. |
| `sites/site-id.json` | Flat JSON array — the ID registry. |
| `assets/flyers/` | All generated flyer TIFFs and PNGs. |

---

## Print Specifications (A5)

| Property | Value |
|---|---|
| **Trim size** | 148 × 210 mm |
| **Canvas with bleed** | 154 × 216 mm (3 mm per side) |
| **Pixels at 300 DPI** | 1819 × 2551 px |
| **DPI** | 300 (embedded in metadata) |
| **Color space** | CMYK (TIFF output) |
| **ICC profile (coated)** | FOGRA39L (`assets/icc/FOGRA39L_coated.icc`) |
| **ICC profile (uncoated)** | FOGRA47L (`assets/icc/FOGRA47L_uncoated.icc`) |
| **Safe area** | 5 mm inset from trim (≈94 px from canvas edge) |
| **Output format** | TIFF (print) + PNG (web preview) |
| **Min font size** | ≥ 4 pt |
| **Min line weight** | ≥ 0.5 pt |

---

## Template Geometry (300 DPI)

The QR code is pasted into a pre-measured box inside the 1819×2551 template:

```
Template   : 1819×2551 px @ 300 DPI
QR box     : x=115, y=1640, width=367, height=367 px
QR inset   : 6 px (padding inside the box)
QR size    : 355×355 px
ID text    : "ID: 00A" at (94, 2457) in soft gray #B4AAA0
Safe area  : 94 px from each edge (bleed 35 px + margin 59 px)
```

---

## ID Format

Short IDs follow the pattern **`NNL`** (two digits + one uppercase letter):

```
00A → 00B → … → 00Z → 01A → … → 99Z
```

Total capacity: **2600 unique IDs**.

---

## QR URL Priority (in `create.sh`)

```
1. SITE_URLID set? → use short redirect  (e.g. https://texngo.it/00A.html)
2. REMOTE_SITE_URL set? → use slug URL   (e.g. https://texngo.it/ristorante-da-mario/)
3. Neither set? → https://<slug>.texngo.it
```

---

## DEV vs PROD — Registry Isolation

By default, `MODE=DEV` or `MODE=MOCKUP` uses `sites/site-id-dev.json`,
while `MODE=PROD` (or unset) uses `sites/site-id.json`.

```bash
# Explicit override:
SITE_ID_REGISTRY=sites/site-id-dev.json uv run scripts/id_manager.py list

# Or just set MODE:
MODE=DEV uv run scripts/make_flyer.py --site-id "00A-00E" --force --remote-url "https://dev.texngo.it"
```

---

## `id_manager.py` — Full CLI Reference

Run from the project root via `uv`:

```bash
uv run scripts/id_manager.py <action> [options]
```

### `allocate` — Auto-assign the next available ID

```bash
uv run scripts/id_manager.py allocate \
  --business "Ristorante Da Mario" \
  --remote-url "http://dev.texngo.it"
```

- If the slug already has an ID → **idempotent, returns the existing entry**.
- Otherwise assigns the next ID after the highest in the registry.

**Output (key=value for shell eval):**

```
SITE_ID=00A
URLID=http://dev.texngo.it/00A.html
URL=http://dev.texngo.it/ristorante-da-mario/index.html
SLUG=ristorante-da-mario
```

---

### `assign` — Manually assign a specific ID

```bash
uv run scripts/id_manager.py assign \
  --id 05B \
  --business "Hotel Lusso" \
  --remote-url "http://dev.texngo.it"
```

- Fails if that ID is already taken by a **different** slug.
- Idempotent if called again for the same slug.

---

### `lookup` — Find an entry by ID or slug

```bash
# By short ID:
uv run scripts/id_manager.py lookup --id 00A

# By site slug:
uv run scripts/id_manager.py lookup --slug ristorante-da-mario
```

Exits 1 with `NOT_FOUND` if nothing matches.

---

### `unassign` — Free an ID (remove from registry)

```bash
# By short ID:
uv run scripts/id_manager.py unassign --id 00A

# By site slug:
uv run scripts/id_manager.py unassign --slug ristorante-da-mario
```

- Removes the entry from the registry JSON.
- The freed ID can be re-used by the next `allocate` call.
- **Does not delete** any files on disk (`sites/<slug>/`, flyers, etc.).

---

### `update` — Change the URL for an existing entry

```bash
uv run scripts/id_manager.py update \
  --id 00A \
  --remote-url "https://my-real-domain.it"

# Or by slug:
uv run scripts/id_manager.py update \
  --slug ristorante-da-mario \
  --remote-url "https://my-real-domain.it"
```

- Updates both `url` and `url_id` in the registry for the matched entry.
- Useful when promoting a site from DEV URL to PROD URL.
- You should then re-run `make_flyer.py` to regenerate the flyer with the new QR code.

---

### `list` — Show all registry entries

```bash
uv run scripts/id_manager.py list
```

Prints a human-readable table of all IDs, slugs, and URLs in the current registry.

---

## `make_flyer.py` — Full CLI Reference

```bash
uv run scripts/make_flyer.py [options]
```

### Key arguments

| Argument | Description |
|---|---|
| `--site-id` | Single ID (`00A`), range (`00A-00E`), or mixed (`00A-00E,01A`) |
| `--force` | Pre-create: register missing IDs as placeholders |
| `--remote-url` | Base URL for QR codes with `--force` (e.g. `https://texngo.it`) |
| `--name` | Business name (single-flyer mode) |
| `--url` | QR code URL (single-flyer mode) |
| `--format` | `tiff` (CMYK print), `png` (RGB), `both` (default) |
| `--paper` | `coated` (FOGRA39L, default) or `uncoated` (FOGRA47L) |
| `--template` | Custom template path (default: `assets/template-flyer-300dpi.png`) |
| `--output-dir` | Output directory (default: `assets/flyers/`) |
| `--dpi` | DPI override (default: 300) |

---

## `create.sh` — Flyer Output Split

When `create.sh` builds a site, it generates both formats:

| Format | Location | Purpose |
|---|---|---|
| **TIFF** (CMYK) | `assets/flyers/flyer-<ID>.tiff` | Send to print shop |
| **PNG** (RGB) | `sites/<slug>/assets/flyer-<ID>.png` | Web preview / download |

---

## FastAPI Endpoint (planned)

```
GET /flyer/{identifier}
```

Where `identifier` is either a short ID (`00A`) or a site slug (`ristorante-da-mario`).

| Query Param | Default | Description |
|---|---|---|
| `download` | `true` | Force file download vs inline view |
| `url` | `""` | Override QR URL (regenerates flyer) |

Returns: **PNG file** (200) or 404/500.

---

## Batch Testing Example

Generate and download flyers for 10 sites via the API:

```bash
TOKEN="your-token"
BASE="http://localhost:8000"

for ID in 00A 00B 00C 00D 00E 00F 00G 00H 00I 00J; do
  curl -s -H "Authorization: Bearer $TOKEN" \
       -o "test-flyer-${ID}.png" \
       "$BASE/flyer/$ID" && echo "✅ $ID"
done
```

Or by slug from a list:

```bash
while IFS= read -r SLUG; do
  curl -s -H "Authorization: Bearer $TOKEN" \
       -o "flyer-${SLUG}.png" \
       "$BASE/flyer/$SLUG"
done < slugs.txt
```
