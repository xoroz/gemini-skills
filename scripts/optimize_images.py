#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow",
# ]
# ///
"""
Optimize images for web delivery.

Converts PNG/JPEG images to WebP format with configurable quality.
Can process individual files or entire directories.

Usage:
    uv run scripts/optimize_images.py --input sites/my-site/assets/ --quality 80
    uv run scripts/optimize_images.py --input image.png --quality 85 --max-width 1200
    uv run scripts/optimize_images.py --input sites/my-site/assets/ --quality 80 --replace
"""

import argparse
import os
import sys
from pathlib import Path

from PIL import Image


def optimize_image(
    input_path: str,
    quality: int = 80,
    max_width: int = 1920,
    max_height: int = 1080,
    replace: bool = False,
    output_dir: str | None = None,
) -> dict:
    """
    Optimize a single image for web.
    
    - Converts to WebP
    - Resizes if larger than max dimensions (preserving aspect ratio)
    - Returns stats dict with original/optimized sizes
    """
    input_path = Path(input_path)
    if not input_path.exists():
        print(f"  ⚠️  File not found: {input_path}", file=sys.stderr)
        return {"skipped": True}

    # Skip non-image files
    if input_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff"):
        return {"skipped": True}

    # Skip already-optimized WebP files
    if input_path.suffix.lower() == ".webp":
        return {"skipped": True}

    try:
        img = Image.open(input_path)
        original_size = input_path.stat().st_size
        orig_w, orig_h = img.size

        # Resize if needed (preserve aspect ratio)
        if orig_w > max_width or orig_h > max_height:
            img.thumbnail((max_width, max_height), Image.LANCZOS)

        # Determine output path
        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            webp_path = out_dir / f"{input_path.stem}.webp"
        else:
            webp_path = input_path.with_suffix(".webp")

        # Save as WebP
        img.save(webp_path, "WEBP", quality=quality, method=4)
        optimized_size = webp_path.stat().st_size

        # Calculate savings
        savings = original_size - optimized_size
        savings_pct = (savings / original_size) * 100 if original_size > 0 else 0

        result = {
            "input": str(input_path),
            "output": str(webp_path),
            "original_size": original_size,
            "optimized_size": optimized_size,
            "savings_bytes": savings,
            "savings_pct": savings_pct,
            "original_dims": f"{orig_w}x{orig_h}",
            "optimized_dims": f"{img.size[0]}x{img.size[1]}",
            "skipped": False,
        }

        # If --replace: remove original PNG and keep only WebP
        if replace:
            input_path.unlink()
            result["replaced"] = True

        return result

    except Exception as e:
        print(f"  ❌ Error optimizing {input_path}: {e}", file=sys.stderr)
        return {"skipped": True, "error": str(e)}


def optimize_directory(
    dir_path: str,
    quality: int = 80,
    max_width: int = 1920,
    max_height: int = 1080,
    replace: bool = False,
) -> list[dict]:
    """Optimize all images in a directory."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        print(f"  ❌ Not a directory: {dir_path}", file=sys.stderr)
        return []

    results = []
    image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    files = sorted(f for f in dir_path.iterdir() if f.suffix.lower() in image_exts)

    for f in files:
        result = optimize_image(str(f), quality, max_width, max_height, replace)
        if not result.get("skipped"):
            results.append(result)

    return results


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def main():
    parser = argparse.ArgumentParser(description="Optimize images for web (PNG/JPEG → WebP)")
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--quality", type=int, default=80, help="WebP quality 1-100 (default: 80)")
    parser.add_argument("--max-width", type=int, default=1920, help="Max width in pixels (default: 1920)")
    parser.add_argument("--max-height", type=int, default=1080, help="Max height in pixels (default: 1080)")
    parser.add_argument("--replace", action="store_true", help="Remove original files after conversion")

    args = parser.parse_args()
    input_path = Path(args.input)

    print(f"🖼️  Optimizing images → WebP (quality={args.quality}, max={args.max_width}x{args.max_height})")

    if input_path.is_dir():
        results = optimize_directory(str(input_path), args.quality, args.max_width, args.max_height, args.replace)
    elif input_path.is_file():
        result = optimize_image(str(input_path), args.quality, args.max_width, args.max_height, args.replace)
        results = [result] if not result.get("skipped") else []
    else:
        print(f"❌ Path not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("  ℹ️  No images to optimize.")
        return

    total_original = sum(r["original_size"] for r in results)
    total_optimized = sum(r["optimized_size"] for r in results)
    total_savings = total_original - total_optimized

    for r in results:
        name = Path(r["input"]).name
        print(
            f"  ✅ {name:20s} → {Path(r['output']).name:24s}"
            f"  {_human_size(r['original_size']):>7s} → {_human_size(r['optimized_size']):>7s}"
            f"  ({r['savings_pct']:.0f}% saved)"
        )

    print()
    print(f"  📊 Total: {_human_size(total_original)} → {_human_size(total_optimized)}")
    savings_pct = (total_savings / total_original) * 100 if total_original > 0 else 0
    print(f"  💾 Saved: {_human_size(total_savings)} ({savings_pct:.0f}%)")
    if args.replace:
        print(f"  🗑️  Original PNGs removed (--replace)")


if __name__ == "__main__":
    main()
