# TexNGo Flyer System

Complete reference for the flyer generation pipeline, ID registry, and the `id_manager.py` CLI tool.

---

## Architecture Overview

```
sites/site-id.json          ← registry (ID ↔ slug ↔ URL mapping)
        ↓  read/write
scripts/id_manager.py       ← CLI: allocate / assign / lookup / unassign / update
        ↓  called by
create.sh  (step 9)         ← auto-runs make_flyer.py every build
create_assets.sh            ← manual standalone wrapper
        ↓
scripts/make_flyer.py       ← opens template, generates QR, pastes it, stamps ID
        ↓
assets/flyers/flyer-<slug>.png        ← global output (one file per client)
sites/<slug>/assets/flyer-<slug>.png  ← copy lives with the site
```

**Cost: $0.00** — no AI calls, purely local Pillow + qrcode rendering.

---

## Files

| File | Purpose |
|---|---|
| `assets/template-flyer.png` | Branded A5 master (1080×1350 px). Has a QR placeholder box at lower-left. |
| `scripts/make_flyer.py` | Stamps QR code (and optional Site ID text) onto the template. |
| `scripts/id_manager.py` | CRUD for `sites/site-id.json`. |
| `sites/site-id.json` | Flat JSON array — the ID registry. |
| `create_assets.sh` | Quick manual flyer re-generation from CLI. |
| `assets/flyers/` | All generated flyer PNGs. |

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
1. SITE_URLID set? → use short redirect  (e.g. http://dev.texngo.it/00A.html)
2. REMOTE_SITE_URL set? → use slug URL   (e.g. http://dev.texngo.it/ristorante-da-mario/)
3. Neither set? → https://<slug>.texngo.it
```

---

## Template Geometry

The QR code is pasted into a pre-measured box inside the 1080×1350 template:

```
QR box  : x=68, y=868, width=218, height=218 px
Inset   : 4 px (padding inside the box)
QR size : 210×210 px
ID text : "ID: 00A" at (14, h-30) in soft gray #B4AAA0
```

---

## DEV vs PROD — Registry Isolation

By default both DEV and PROD runs write to the same `sites/site-id.json`.
This pollutes real production IDs with test entries.

### Solution: `SITE_ID_REGISTRY` environment variable

`id_manager.py` reads the registry path from `SITE_ID_REGISTRY` if set:

```bash
# In .env (or export in shell):
SITE_ID_REGISTRY=sites/site-id-dev.json    # for MODE=DEV / test runs
# SITE_ID_REGISTRY=sites/site-id.json      # default (production)
```

Or per-run:

```bash
SITE_ID_REGISTRY=sites/site-id-dev.json MODE=DEV ./create.sh "Test Salon" ...
```

`create.sh` forwards the env var automatically because Python inherits the environment.

### Recommended `.env` setup

```ini
# .env (DEV machine / test workflow)
MODE=DEV
SITE_ID_REGISTRY=sites/site-id-dev.json

# .env (production server)
MODE=PROD
# SITE_ID_REGISTRY not set → defaults to sites/site-id.json
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
- You should then re-run `create_assets.sh` or call `POST /flyer/{id}` from the API to regenerate the flyer with the new QR code.

---

### `list` — Show all registry entries

```bash
uv run scripts/id_manager.py list
```

Prints a human-readable table of all IDs, slugs, and URLs in the current registry.

---

## `create_assets.sh` — Manual Flyer Re-generation

```bash
./create_assets.sh "Business Name" "https://preview-url.texngo.it"
```

Outputs to `assets/flyers/flyer-<slug>.png` and copies to `sites/<slug>/` if that folder exists.

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
