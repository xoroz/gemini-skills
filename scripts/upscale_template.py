#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow",
# ]
# ///
"""
Upscale the flyer template from 1080×1350 (social) → A5 print dimensions.

Target: 1819 × 2551 px  (A5 148×210 mm + 3mm bleed, at 300 DPI)

Since the aspect ratios differ (current 0.80 vs A5 0.71), this script:
  1. Upscales to match the target height (2551 px)
  2. Center-crops the width to 1819 px
  3. Sets DPI metadata to 300

Usage:
    uv run scripts/upscale_template.py \
        --input  assets/template-flyer.png \
        --output assets/template-flyer-300dpi.png
"""
from __future__ import annotations

import argparse
from PIL import Image


def upscale_a5(input_path: str, output_path: str) -> None:
    """Upscale template to A5 + 3mm bleed at 300 DPI."""
    # Target dimensions: A5 (148×210 mm) + 3mm bleed each side → 154×216 mm
    TARGET_W = round((148 + 6) / 25.4 * 300)   # 1819 px
    TARGET_H = round((210 + 6) / 25.4 * 300)   # 2551 px

    img = Image.open(input_path).convert("RGB")
    w, h = img.size
    print(f"📐 Source:  {w}×{h} px  (ratio {w/h:.4f})")
    print(f"📐 Target:  {TARGET_W}×{TARGET_H} px  (ratio {TARGET_W/TARGET_H:.4f})")

    # Strategy: scale to match target height, then center-crop width
    scale = TARGET_H / h
    new_w = round(w * scale)
    new_h = TARGET_H
    print(f"📐 Scaled:  {new_w}×{new_h} px  (scale {scale:.3f}×)")

    img_scaled = img.resize((new_w, new_h), Image.LANCZOS)

    # Center-crop width
    if new_w > TARGET_W:
        left = (new_w - TARGET_W) // 2
        img_cropped = img_scaled.crop((left, 0, left + TARGET_W, TARGET_H))
        print(f"✂️  Cropped: {new_w} → {TARGET_W} px width (removed {new_w - TARGET_W} px, {left} px each side)")
    elif new_w < TARGET_W:
        # Pad with background color (sample from top-left corner)
        bg = img_scaled.getpixel((5, 5))
        canvas = Image.new("RGB", (TARGET_W, TARGET_H), bg)
        offset = (TARGET_W - new_w) // 2
        canvas.paste(img_scaled, (offset, 0))
        img_cropped = canvas
        print(f"📏 Padded:  {new_w} → {TARGET_W} px width (added {TARGET_W - new_w} px)")
    else:
        img_cropped = img_scaled

    # Save with 300 DPI metadata
    img_cropped.save(output_path, "PNG", dpi=(300, 300))
    final_w, final_h = img_cropped.size
    print(f"✅ Saved:   {output_path}")
    print(f"   Size:    {final_w}×{final_h} px @ 300 DPI")
    print(f"   Print:   {final_w/300*25.4:.1f}×{final_h/300*25.4:.1f} mm")


def main() -> None:
    ap = argparse.ArgumentParser(description="Upscale flyer template to A5 @ 300 DPI")
    ap.add_argument("--input",  required=True, help="Source template PNG")
    ap.add_argument("--output", required=True, help="Output upscaled PNG")
    args = ap.parse_args()
    upscale_a5(args.input, args.output)


if __name__ == "__main__":
    main()
