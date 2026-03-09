#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow",
#     "qrcode",
# ]
# ///
"""
TexNGo Flyer Stamp — Print-ready A5 flyer generator.

Takes the template (assets/template-flyer-300dpi.png) and composites
a QR code into the placeholder area.  Output is print-ready:

  • 300 DPI  (A5 + 3 mm bleed = 1819 × 2551 px)
  • CMYK via ICC profile  (FOGRA39L coated / FOGRA47L uncoated)
  • Output as TIFF (CMYK) + PNG (RGB preview)

Supports batch mode via range syntax:
    --site-id 00A-00E         → flyers for 00A, 00B, 00C, 00D, 00E
    --site-id 00A             → single flyer for 00A
    --site-id 00A-00E,01A     → range + individual (comma-separated)

In batch mode the script reads business names and URLs from the
site-id registry (sites/site-id.json), so --name and --url are
not required.

Single-flyer usage (backwards compatible):
    uv run scripts/make_flyer.py \\
        --name "Marble Nails di Bertola Giada" \\
        --url  "https://marble-nails-di-bertola-giada.texngo.it" \\
        --template assets/template-flyer-300dpi.png \\
        --output  assets/flyers/flyer-marble-nails-di-bertola-giada.png

Batch usage:
    uv run scripts/make_flyer.py \\
        --site-id "00A-00E" \\
        --template assets/template-flyer-300dpi.png \\
        --output-dir assets/flyers

Print-quality options:
    --format tiff             # tiff (CMYK, default), png (RGB), both
    --paper  coated           # coated (FOGRA39L, default) or uncoated (FOGRA47L)
    --dpi    300              # default 300
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import qrcode
from qrcode.image.pil import PilImage
from PIL import Image, ImageDraw, ImageFont

# Try to import ImageCms for CMYK conversion
try:
    from PIL import ImageCms
    HAS_CMS = True
except ImportError:
    HAS_CMS = False

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# ---------------------------------------------------------------------------
# Load .env from project root (simple key=value parser, no dependencies)
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

_load_dotenv()

# ---------------------------------------------------------------------------
# Print specs — A5 + 3 mm bleed @ 300 DPI
# ---------------------------------------------------------------------------
DPI          = 300
# A5 trim size: 148 × 210 mm
TRIM_W_MM    = 148.0
TRIM_H_MM    = 210.0
BLEED_MM     =   3.0
# Total canvas including bleed
CANVAS_W_MM  = TRIM_W_MM + 2 * BLEED_MM  # 154 mm
CANVAS_H_MM  = TRIM_H_MM + 2 * BLEED_MM  # 216 mm
CANVAS_W_PX  = round(CANVAS_W_MM / 25.4 * DPI)  # 1819 px
CANVAS_H_PX  = round(CANVAS_H_MM / 25.4 * DPI)  # 2551 px
BLEED_PX     = round(BLEED_MM / 25.4 * DPI)      # ~35 px
SAFE_MM      = 5.0   # keep critical content this far from trim edge
SAFE_PX      = round(SAFE_MM / 25.4 * DPI)       # ~59 px
SAFE_INSET   = BLEED_PX + SAFE_PX                 # ~94 px from canvas edge

# ---------------------------------------------------------------------------
# Default QR placeholder coordinates — measured against 1819×2551 template.
# Scaled from old 1080×1350 coords by factor ≈1.684 (width) / 1.890 (height)
#
# In the upscaled template the QR placeholder sits roughly here:
# ---------------------------------------------------------------------------
DEFAULT_QR_BOX_X = 115     # px — left edge
DEFAULT_QR_BOX_Y = 1640    # px — top edge
DEFAULT_QR_BOX_W = 367     # px — area width
DEFAULT_QR_BOX_H = 367     # px — area height
DEFAULT_QR_INSET =   6     # px — padding inside QR box

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------
BRAND_DARK = "#3D3225"

# ---------------------------------------------------------------------------
# ICC profile paths — project-local first, system fallback
# ---------------------------------------------------------------------------
def _resolve_icc(filename: str) -> str:
    """Find an ICC profile: project assets/icc/ first, then system."""
    local = PROJECT_DIR / "assets" / "icc" / filename
    if local.is_file():
        return str(local)
    system = Path("/usr/share/color/icc/colord") / filename
    if system.is_file():
        return str(system)
    return str(local)  # will trigger a "not found" warning later

ICC_PATHS = {
    "coated":   _resolve_icc("FOGRA39L_coated.icc"),
    "uncoated": _resolve_icc("FOGRA47L_uncoated.icc"),
}

# ---------------------------------------------------------------------------
# ID arithmetic (mirrors id_manager.py)
# ---------------------------------------------------------------------------

def _id_to_int(site_id: str) -> int:
    """Convert a short ID like '05A' to a sortable integer (0-2599)."""
    num    = int(site_id[:2])
    letter = ord(site_id[2].upper()) - ord("A")
    return num * 26 + letter


def _int_to_id(n: int) -> str:
    """Convert integer (0-2599) back to a short ID like '05A'."""
    num    = n // 26
    letter = chr(ord("A") + n % 26)
    return f"{num:02d}{letter}"


def _parse_id_spec(spec: str) -> list[str]:
    """
    Parse a site-id specification into a list of IDs.

    Supports:
        "00A"           → ["00A"]
        "00A-00E"       → ["00A", "00B", "00C", "00D", "00E"]
        "00A-00E,01A"   → ["00A", "00B", "00C", "00D", "00E", "01A"]
        "00A,00C,01Z"   → ["00A", "00C", "01Z"]
    """
    result: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # Range: "00A-00E"
            pieces = part.split("-", 1)
            start_str = pieces[0].strip().upper()
            end_str   = pieces[1].strip().upper()

            if not re.match(r"^\d{2}[A-Z]$", start_str):
                print(f"❌ Invalid range start: '{start_str}'", file=sys.stderr)
                sys.exit(1)
            if not re.match(r"^\d{2}[A-Z]$", end_str):
                print(f"❌ Invalid range end: '{end_str}'", file=sys.stderr)
                sys.exit(1)

            start_int = _id_to_int(start_str)
            end_int   = _id_to_int(end_str)

            if end_int < start_int:
                print(f"❌ Range end '{end_str}' is before start '{start_str}'", file=sys.stderr)
                sys.exit(1)

            for i in range(start_int, end_int + 1):
                result.append(_int_to_id(i))
        else:
            # Single ID
            single = part.upper()
            if not re.match(r"^\d{2}[A-Z]$", single):
                print(f"❌ Invalid ID format: '{single}'", file=sys.stderr)
                sys.exit(1)
            result.append(single)

    return result


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _registry_path() -> Path:
    """Resolve registry file path (same logic as id_manager.py)."""
    reg_env = os.environ.get("SITE_ID_REGISTRY", "")
    mode    = os.environ.get("MODE", "PROD").upper()
    if reg_env:
        return PROJECT_DIR / reg_env
    elif mode in ("DEV", "MOCKUP"):
        return PROJECT_DIR / "sites" / "site-id-dev.json"
    else:
        return PROJECT_DIR / "sites" / "site-id.json"


def _load_registry() -> list[dict]:
    """Load the site-id registry JSON."""
    path = _registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(entries: list[dict]) -> None:
    """Write the registry back to disk."""
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _slugify(name: str) -> str:
    """Mirror create.sh slug logic."""
    s = name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def _lookup_id(registry: list[dict], site_id: str) -> dict | None:
    """Find a registry entry by ID."""
    for entry in registry:
        if entry.get("id", "").upper() == site_id.upper():
            return entry
    return None


def _force_register(registry: list[dict], site_id: str, remote_url: str) -> dict:
    """Create a placeholder registry entry for pre-printing."""
    remote_url = remote_url.rstrip("/")
    entry = {
        "id":            site_id,
        "business_name": f"(reserved {site_id})",
        "slug":          f"reserved-{site_id.lower()}",
        "url":           "",
        "url_id":        f"{remote_url}/{site_id}.html" if remote_url else f"{site_id}.html",
    }
    registry.append(entry)
    _save_registry(registry)
    return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _make_qr(url: str, size: int) -> Image.Image:
    """Generate a square QR code image at the given pixel size."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(
        image_factory=PilImage,
        fill_color=_hex_to_rgb(BRAND_DARK),
        back_color=(248, 242, 252),
    ).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a clean TTF font, fall back to default."""
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _convert_to_cmyk(
    image: Image.Image,
    paper: str = "coated",
) -> Image.Image | None:
    """
    Convert an RGB image to CMYK using the appropriate ICC profile.
    Returns None if CMS is unavailable or profile not found.
    """
    if not HAS_CMS:
        print("   ⚠️  ImageCms not available — skipping CMYK conversion")
        return None

    icc_path = ICC_PATHS.get(paper)
    if not icc_path or not os.path.isfile(icc_path):
        print(f"   ⚠️  ICC profile not found: {icc_path} — skipping CMYK conversion")
        return None

    try:
        srgb_profile = ImageCms.createProfile("sRGB")
        cmyk_profile = ImageCms.getOpenProfile(icc_path)
        transform = ImageCms.buildTransform(
            srgb_profile, cmyk_profile,
            "RGB", "CMYK",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        )
        cmyk_img = ImageCms.applyTransform(image, transform)
        return cmyk_img
    except Exception as e:
        print(f"   ⚠️  CMYK conversion failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Core: stamp one flyer
# ---------------------------------------------------------------------------

def stamp_flyer(
    *,
    template_path: str,
    url: str,
    output_path: str,
    qr_box_x: int = DEFAULT_QR_BOX_X,
    qr_box_y: int = DEFAULT_QR_BOX_Y,
    qr_box_w: int = DEFAULT_QR_BOX_W,
    qr_box_h: int = DEFAULT_QR_BOX_H,
    qr_inset: int = DEFAULT_QR_INSET,
    site_id: str | None = None,
    output_format: str = "both",
    paper: str = "coated",
    dpi: int = DPI,
) -> None:
    """Load template, generate QR, paste, save in print-ready format."""

    # ── Load template ─────────────────────────────────────────────────────
    if not os.path.isfile(template_path):
        print(f"❌  Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    canvas = Image.open(template_path).convert("RGB")
    w, h = canvas.size

    # ── Generate QR ───────────────────────────────────────────────────────
    qr_size = min(qr_box_w, qr_box_h) - qr_inset * 2
    qr_img  = _make_qr(url, qr_size)

    # ── Paste QR – centered inside the box ────────────────────────────────
    paste_x = qr_box_x + qr_inset + (qr_box_w - qr_inset * 2 - qr_size) // 2
    paste_y = qr_box_y + qr_inset + (qr_box_h - qr_inset * 2 - qr_size) // 2
    canvas.paste(qr_img, (paste_x, paste_y))

    # ── Stamp Site ID (soft, bottom-left, inside safe area) ───────────────
    if site_id:
        draw = ImageDraw.Draw(canvas)
        font_size = round(18 * (h / 1350))  # scale with template height
        font = _get_font(font_size)

        id_text = f"ID: {site_id}"
        text_x = SAFE_INSET
        text_y = h - SAFE_INSET
        id_color = (180, 170, 160)
        draw.text((text_x, text_y), id_text, fill=id_color, font=font)
        print(f"   ID stamp : '{id_text}' at ({text_x}, {text_y})")

    # ── Safe area check ───────────────────────────────────────────────────
    if paste_x < SAFE_INSET:
        print(f"   ⚠️  QR code left edge ({paste_x} px) is inside the safe zone ({SAFE_INSET} px)")
    if paste_y + qr_size > h - SAFE_INSET:
        print(f"   ⚠️  QR code bottom ({paste_y + qr_size} px) is inside the safe zone ({h - SAFE_INSET} px)")

    # ── Save ──────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    base, _ = os.path.splitext(output_path)

    saved_files = []

    # --- RGB PNG (preview / web) ---
    if output_format in ("png", "both"):
        png_path = f"{base}.png"
        canvas.save(png_path, "PNG", dpi=(dpi, dpi))
        saved_files.append(("PNG (RGB preview)", png_path))

    # --- CMYK TIFF (print) ---
    if output_format in ("tiff", "both"):
        cmyk_img = _convert_to_cmyk(canvas, paper=paper)
        tiff_path = f"{base}.tiff"
        if cmyk_img is not None:
            cmyk_img.save(tiff_path, "TIFF", dpi=(dpi, dpi), compression="tiff_lzw")
            saved_files.append(("TIFF (CMYK print)", tiff_path))
        else:
            # Fallback: save RGB TIFF with DPI (better than nothing)
            canvas.save(tiff_path, "TIFF", dpi=(dpi, dpi), compression="tiff_lzw")
            saved_files.append(("TIFF (RGB fallback)", tiff_path))

    # ── Report ────────────────────────────────────────────────────────────
    for label, path in saved_files:
        fsize = os.path.getsize(path)
        fsize_str = f"{fsize / 1024 / 1024:.1f} MB" if fsize > 1024*1024 else f"{fsize / 1024:.0f} KB"
        print(f"   ✅ {label}: {path}  ({fsize_str})")

    print(f"   Template : {w}×{h} px @ {dpi} DPI")
    print(f"   Print    : {w/dpi*25.4:.1f}×{h/dpi*25.4:.1f} mm")
    print(f"   QR box   : x={qr_box_x} y={qr_box_y} {qr_box_w}×{qr_box_h} px")
    print(f"   QR size  : {qr_size}×{qr_size} px  (inset {qr_inset} px)")
    print(f"   Paper    : {paper}  |  ICC: {ICC_PATHS.get(paper, 'N/A')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="TexNGo Flyer Stamp — print-ready A5 flyer with QR code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Batch mode examples:
    --site-id 00A-00E          5 flyers for IDs 00A through 00E
    --site-id 00A-00E,01A      range + individual
    --site-id 00A              single flyer

Pre-print (force-create before sites exist):
    --site-id 00A-00J --force --remote-url https://texngo.it

In batch mode, --name and --url are read from the registry.
With --force, missing IDs are auto-registered as placeholders.
        """,
    )

    # --- Identity ---
    ap.add_argument("--name",     default=None,  help="Business name (single mode)")
    ap.add_argument("--url",      default=None,  help="URL for QR code (single mode)")
    ap.add_argument("--site-id",  default=None,  help="Site ID or range (e.g. 00A, 00A-00E, 00A-00E,01A)")
    ap.add_argument("--force",    action="store_true",
                    help="Force-create flyers for IDs not yet in registry (pre-print mode)")
    ap.add_argument("--remote-url", default=os.environ.get("REMOTE_SITE_URL", ""),
                    help="Base URL for QR codes (default: $REMOTE_SITE_URL from .env)")

    # --- Paths ---
    ap.add_argument("--template", default=None,
                    help="Path to template PNG (default: assets/template-flyer-300dpi.png)")
    ap.add_argument("--output",   default=None,  help="Output file path (single mode)")
    ap.add_argument("--output-dir", default=None, help="Output directory (batch mode, default: assets/flyers)")

    # --- QR fine-tuning ---
    ap.add_argument("--qr-box-x", type=int, default=DEFAULT_QR_BOX_X)
    ap.add_argument("--qr-box-y", type=int, default=DEFAULT_QR_BOX_Y)
    ap.add_argument("--qr-box-w", type=int, default=DEFAULT_QR_BOX_W)
    ap.add_argument("--qr-box-h", type=int, default=DEFAULT_QR_BOX_H)
    ap.add_argument("--qr-inset", type=int, default=DEFAULT_QR_INSET)

    # --- Print quality ---
    ap.add_argument("--format", dest="output_format", default="both",
                    choices=["png", "tiff", "both"],
                    help="Output format: png (RGB), tiff (CMYK), both (default)")
    ap.add_argument("--paper", default="coated",
                    choices=["coated", "uncoated"],
                    help="Paper type for ICC profile (default: coated = FOGRA39L)")
    ap.add_argument("--dpi", type=int, default=DPI, help="DPI (default: 300)")

    args = ap.parse_args()

    # Resolve template path
    template = args.template or str(PROJECT_DIR / "assets" / "template-flyer-300dpi.png")
    # Fall back to old template if 300dpi version doesn't exist
    if not os.path.isfile(template):
        fallback = str(PROJECT_DIR / "assets" / "template-flyer.png")
        if os.path.isfile(fallback):
            print(f"⚠️  300 DPI template not found, falling back to: {fallback}")
            template = fallback
        else:
            print(f"❌ Template not found: {template}", file=sys.stderr)
            sys.exit(1)

    # --- Determine mode: batch or single ---
    if args.site_id:
        ids = _parse_id_spec(args.site_id)

        if len(ids) == 1 and args.name and args.url:
            # Single mode with explicit name/url (backwards compatible)
            out = args.output or str(
                Path(args.output_dir or str(PROJECT_DIR / "assets" / "flyers"))
                / f"flyer-{ids[0]}.png"
            )
            print(f"🎨 Stamping flyer for: {args.name}")
            print(f"   URL : {args.url}")
            print(f"   ID  : {ids[0]}")
            stamp_flyer(
                template_path=template,
                url=args.url,
                output_path=out,
                qr_box_x=args.qr_box_x,
                qr_box_y=args.qr_box_y,
                qr_box_w=args.qr_box_w,
                qr_box_h=args.qr_box_h,
                qr_inset=args.qr_inset,
                site_id=ids[0],
                output_format=args.output_format,
                paper=args.paper,
                dpi=args.dpi,
            )
            return

        # Batch mode — look up from registry (or force-create)
        registry = _load_registry()
        force    = args.force

        if not registry and not force:
            print("❌ Registry is empty or not found. Cannot resolve IDs.", file=sys.stderr)
            print("   Hint: use --force to pre-create, or run create.sh first.", file=sys.stderr)
            sys.exit(1)

        out_dir = Path(args.output_dir or str(PROJECT_DIR / "assets" / "flyers"))
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"🖨️  Batch flyer generation: {len(ids)} flyer(s)")
        print(f"   IDs:      {ids[0]} → {ids[-1]}  ({len(ids)} total)")
        print(f"   Template: {template}")
        print(f"   Output:   {out_dir}/")
        print(f"   Format:   {args.output_format}  |  Paper: {args.paper}  |  DPI: {args.dpi}")
        if force:
            print(f"   Mode:     🔧 FORCE (pre-print — missing IDs will be registered)")
            print(f"   QR base:  {args.remote_url or '(none — relative URLs)'}")
        print()

        success  = 0
        skipped  = 0
        created  = 0
        for i, sid in enumerate(ids, 1):
            entry = _lookup_id(registry, sid)

            if not entry and not force:
                print(f"  ⏭️  [{i}/{len(ids)}] {sid} — not in registry, skipping")
                skipped += 1
                continue

            if not entry and force:
                # Auto-register placeholder
                entry = _force_register(registry, sid, args.remote_url)
                created += 1
                print(f"  📝 [{i}/{len(ids)}] {sid} — registered as placeholder")
            else:
                print(f"  🎨 [{i}/{len(ids)}] {sid} — {entry.get('business_name', sid)}")

            biz_name = entry.get("business_name", sid)
            slug     = entry.get("slug", sid.lower())
            url      = entry.get("url_id") or entry.get("url") or f"{args.remote_url.rstrip('/')}/{sid}.html"
            out_path = str(out_dir / f"flyer-{sid}")  # extension added by stamp_flyer

            print(f"   URL : {url}")

            stamp_flyer(
                template_path=template,
                url=url,
                output_path=out_path,
                qr_box_x=args.qr_box_x,
                qr_box_y=args.qr_box_y,
                qr_box_w=args.qr_box_w,
                qr_box_h=args.qr_box_h,
                qr_inset=args.qr_inset,
                site_id=sid,
                output_format=args.output_format,
                paper=args.paper,
                dpi=args.dpi,
            )
            success += 1
            print()

        print(f"✅ Batch complete: {success} generated, {skipped} skipped, {created} new IDs registered")
        if created:
            print(f"   📋 Registry: {_registry_path()}")

    elif args.name and args.url:
        # Single mode without --site-id
        out = args.output or str(
            Path(args.output_dir or str(PROJECT_DIR / "assets" / "flyers"))
            / "flyer-output.png"
        )
        print(f"🎨 Stamping flyer for: {args.name}")
        print(f"   URL : {args.url}")

        stamp_flyer(
            template_path=template,
            url=args.url,
            output_path=out,
            qr_box_x=args.qr_box_x,
            qr_box_y=args.qr_box_y,
            qr_box_w=args.qr_box_w,
            qr_box_h=args.qr_box_h,
            qr_inset=args.qr_inset,
            site_id=None,
            output_format=args.output_format,
            paper=args.paper,
            dpi=args.dpi,
        )
    else:
        print("❌ Provide either --site-id (batch) or both --name and --url (single).", file=sys.stderr)
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
