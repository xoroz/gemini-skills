#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow",
#     "qrcode",
# ]
# ///
"""
TexNGo Flyer Stamp — Places a QR code onto the existing template flyer.

Takes the ready-made template (assets/template-flyer.png) and
composites a generated QR code into the placeholder box in the lower-left.

Usage:
    uv run scripts/make_flyer.py \
        --name "Marble Nails di Bertola Giada" \
        --url  "https://marble-nails-di-bertola-giada.texngo.it" \
        --template assets/template-flyer.png \
        --output  assets/flyers/flyer-marble-nails-di-bertola-giada.png

Optional fine-tuning:
    --qr-x 55   --qr-y 875   # top-left corner of the QR box (pixels)
    --qr-size 205             # pixel side length of the QR image to paste
"""

from __future__ import annotations

import argparse
import os
import sys

import qrcode
from qrcode.image.pil import PilImage
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Default QR placeholder coordinates (measured against 1080×1350 template).
# The purple-bordered "QR CODE" box sits roughly here:
#   left ~48 px, top ~868 px, box is ~218×218 px
# We paste the QR image inside with a small inset.
# ---------------------------------------------------------------------------
DEFAULT_QR_BOX_X = 68    # px — left edge of the QR placement area
DEFAULT_QR_BOX_Y = 868   # px — top  edge of the QR placement area
DEFAULT_QR_BOX_W = 218   # px — area width
DEFAULT_QR_BOX_H = 218   # px — area height
DEFAULT_QR_INSET =   4   # px — padding (smaller now, no visible box)

BRAND_DARK   = "#3D3225"
BRAND_BLUE   = "#2563EB"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _make_qr(url: str, size: int) -> Image.Image:
    """Generate a square QR code image."""
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
        back_color=(248, 242, 252),   # matches the template's soft off-white
    ).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def stamp_flyer(
    *,
    template_path: str,
    url: str,
    output_path: str,
    qr_box_x: int = DEFAULT_QR_BOX_X,
    qr_box_y: int = DEFAULT_QR_BOX_Y,
    qr_box_w: int = DEFAULT_QR_BOX_W,
    qr_box_h: int = DEFAULT_QR_BOX_H,
    qr_inset:  int = DEFAULT_QR_INSET,
) -> None:
    """Load template, generate QR, paste, save."""
    # ── Load template ──────────────────────────────────────────────────────
    if not os.path.isfile(template_path):
        print(f"❌  Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    canvas = Image.open(template_path).convert("RGB")
    w, h = canvas.size

    # ── Generate QR ────────────────────────────────────────────────────────
    qr_size = min(qr_box_w, qr_box_h) - qr_inset * 2
    qr_img  = _make_qr(url, qr_size)

    # ── Paste – centered inside the box ───────────────────────────────────
    paste_x = qr_box_x + qr_inset + (qr_box_w - qr_inset * 2 - qr_size) // 2
    paste_y = qr_box_y + qr_inset + (qr_box_h - qr_inset * 2 - qr_size) // 2
    canvas.paste(qr_img, (paste_x, paste_y))

    # ── Save ───────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"✅  Flyer saved → {output_path}")
    print(f"   Template : {w}×{h} px")
    print(f"   QR box   : x={qr_box_x} y={qr_box_y} {qr_box_w}×{qr_box_h} px")
    print(f"   QR size  : {qr_size}×{qr_size} px  (inset {qr_inset} px)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stamp a QR code onto the TexNGo template flyer.",
    )
    ap.add_argument("--name",     required=True,  help="Business name (used only for log messages)")
    ap.add_argument("--url",      required=True,  help="URL to encode in the QR code")
    ap.add_argument("--template", required=True,  help="Path to template-flyer.png")
    ap.add_argument("--output",   required=True,  help="Path to write the finished flyer PNG")

    # Fine-tuning knobs (rarely needed)
    ap.add_argument("--qr-box-x", type=int, default=DEFAULT_QR_BOX_X)
    ap.add_argument("--qr-box-y", type=int, default=DEFAULT_QR_BOX_Y)
    ap.add_argument("--qr-box-w", type=int, default=DEFAULT_QR_BOX_W)
    ap.add_argument("--qr-box-h", type=int, default=DEFAULT_QR_BOX_H)
    ap.add_argument("--qr-inset", type=int, default=DEFAULT_QR_INSET)

    args = ap.parse_args()

    print(f"🎨  Stamping flyer for: {args.name}")
    print(f"   URL : {args.url}")

    stamp_flyer(
        template_path = args.template,
        url           = args.url,
        output_path   = args.output,
        qr_box_x      = args.qr_box_x,
        qr_box_y      = args.qr_box_y,
        qr_box_w      = args.qr_box_w,
        qr_box_h      = args.qr_box_h,
        qr_inset      = args.qr_inset,
    )


if __name__ == "__main__":
    main()
