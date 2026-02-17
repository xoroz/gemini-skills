#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai",
#     "pillow",
#     "requests",
# ]
# ///
"""
Generate images using Google's Gemini 2.5 Flash (Nano Banana Pro).

Supports two providers:
  1. Google GenAI (GEMINI_API_KEY) - primary
  2. OpenRouter (OPENROUTER_API_KEY) - fallback

Usage:
    uv run image.py --prompt "A colorful abstract pattern" --output "./hero.png"
    uv run image.py --prompt "Minimalist icon" --output "./icon.png" --aspect landscape
    uv run image.py --prompt "Quick draft" --output "./draft.png" --quality draft
    uv run image.py --prompt "Force openrouter" --output "./img.png" --provider openrouter
"""

import argparse
import base64
import json
import os
import sys

import requests as http_requests
from google import genai
from PIL import Image


def get_aspect_instruction(aspect: str) -> str:
    """Return aspect ratio instruction for the prompt."""
    aspects = {
        "square": "Generate a square image (1:1 aspect ratio).",
        "landscape": "Generate a landscape/wide image (16:9 aspect ratio).",
        "portrait": "Generate a portrait/tall image (9:16 aspect ratio).",
    }
    return aspects.get(aspect, aspects["square"])


def get_quality_instruction(quality: str) -> str:
    """Return quality instruction for the prompt."""
    if quality == "draft":
        return "Generate a simple, clean image suitable for a draft/mockup. Keep details minimal but visually clear. Lower detail is fine."
    return ""


def generate_with_gemini(
    prompt: str, output_path: str, aspect: str = "square",
    quality: str = "high", reference: str | None = None,
) -> bool:
    """Generate image using Google GenAI SDK. Returns True on success."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  [gemini] GEMINI_API_KEY not set, skipping.", file=sys.stderr)
        return False

    try:
        client = genai.Client(api_key=api_key)

        aspect_instruction = get_aspect_instruction(aspect)
        quality_instruction = get_quality_instruction(quality)
        full_prompt = f"{aspect_instruction} {quality_instruction} {prompt}".strip()

        # Build contents with optional reference image
        contents: list = []
        if reference:
            if not os.path.exists(reference):
                print(f"  [gemini] Reference image not found: {reference}", file=sys.stderr)
                return False
            ref_image = Image.open(reference)
            contents.append(ref_image)
            full_prompt = f"{full_prompt} Use the provided image as a reference for style, composition, or content."
        contents.append(full_prompt)

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=contents,
        )

        # Extract image from response
        for part in response.parts:
            if part.text is not None:
                print(f"  [gemini] Model response: {part.text}")
            elif part.inline_data is not None:
                image = part.as_image()
                image.save(output_path)
                print(f"  [gemini] Image saved to: {output_path}")
                return True

        print("  [gemini] No image data in response.", file=sys.stderr)
        return False

    except Exception as e:
        print(f"  [gemini] Error: {e}", file=sys.stderr)
        return False


def generate_with_openrouter(
    prompt: str, output_path: str, aspect: str = "square",
    quality: str = "high",
) -> bool:
    """Generate image using OpenRouter API as fallback. Returns True on success."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("  [openrouter] OPENROUTER_API_KEY not set, skipping.", file=sys.stderr)
        return False

    try:
        aspect_instruction = get_aspect_instruction(aspect)
        quality_instruction = get_quality_instruction(quality)
        full_prompt = f"{aspect_instruction} {quality_instruction} {prompt}".strip()

        response = http_requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Title": "Nano Banana Pro",
            },
            data=json.dumps({
                "model": "google/gemini-2.5-flash-image",
                "messages": [
                    {
                        "role": "user",
                        "content": full_prompt,
                    }
                ],
            }),
            timeout=120,
        )

        if response.status_code != 200:
            print(f"  [openrouter] HTTP {response.status_code}: {response.text[:300]}", file=sys.stderr)
            return False

        data = response.json()

        # Check for images in the response
        # OpenRouter returns images as base64 data URLs in message.images
        message = data.get("choices", [{}])[0].get("message", {})

        # Try message.images array first
        images = message.get("images", [])
        if images:
            img_data = images[0]
            if isinstance(img_data, dict):
                img_url = img_data.get("image_url", {}).get("url", "")
            else:
                img_url = img_data
            
            if img_url.startswith("data:"):
                # Extract base64 data from data URL
                b64_data = img_url.split(",", 1)[1]
                img_bytes = base64.b64decode(b64_data)
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                print(f"  [openrouter] Image saved to: {output_path}")
                return True

        # Try content array with image parts
        content = message.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    # Check for image_url type
                    if part.get("type") == "image_url":
                        img_url = part.get("image_url", {}).get("url", "")
                        if img_url.startswith("data:"):
                            b64_data = img_url.split(",", 1)[1]
                            img_bytes = base64.b64decode(b64_data)
                            with open(output_path, "wb") as f:
                                f.write(img_bytes)
                            print(f"  [openrouter] Image saved to: {output_path}")
                            return True
                    # Check for inline_data
                    elif "inline_data" in part:
                        b64_data = part["inline_data"].get("data", "")
                        if b64_data:
                            img_bytes = base64.b64decode(b64_data)
                            with open(output_path, "wb") as f:
                                f.write(img_bytes)
                            print(f"  [openrouter] Image saved to: {output_path}")
                            return True

        # Log what we got for debugging
        text_content = content if isinstance(content, str) else str(content)[:200]
        if text_content:
            print(f"  [openrouter] Model text: {text_content[:200]}")
        print("  [openrouter] No image data in response.", file=sys.stderr)
        return False

    except Exception as e:
        print(f"  [openrouter] Error: {e}", file=sys.stderr)
        return False


def generate_image(
    prompt: str, output_path: str, aspect: str = "square",
    quality: str = "high", reference: str | None = None,
    provider: str = "auto",
) -> None:
    """Generate image with automatic fallback between providers."""
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    providers = {
        "gemini": [generate_with_gemini],
        "openrouter": [generate_with_openrouter],
        "auto": [generate_with_gemini, generate_with_openrouter],
    }

    provider_list = providers.get(provider, providers["auto"])

    for gen_fn in provider_list:
        if gen_fn == generate_with_openrouter:
            # OpenRouter doesn't support reference images via this method
            success = gen_fn(prompt, output_path, aspect, quality)
        else:
            success = gen_fn(prompt, output_path, aspect, quality, reference)

        if success:
            return

    print("Error: All providers failed to generate image.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate images using Gemini 2.5 Flash (Nano Banana Pro)"
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Description of the image to generate",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output file path (PNG format)",
    )
    parser.add_argument(
        "--aspect",
        choices=["square", "landscape", "portrait"],
        default="square",
        help="Aspect ratio (default: square)",
    )
    parser.add_argument(
        "--quality",
        choices=["high", "draft"],
        default="high",
        help="Image quality: 'high' for production, 'draft' for quick mockups (default: high)",
    )
    parser.add_argument(
        "--reference",
        help="Path to a reference image for style/composition guidance (optional, Gemini only)",
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "gemini", "openrouter"],
        default="auto",
        help="Provider to use: 'auto' tries Gemini then OpenRouter, or force one (default: auto)",
    )

    args = parser.parse_args()
    generate_image(
        args.prompt, args.output, args.aspect,
        args.quality, args.reference, args.provider,
    )


if __name__ == "__main__":
    main()
