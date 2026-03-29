#!/usr/bin/env python3
"""
openrouter_gen.py — Minimal OpenRouter text generation.

Usage:
  echo "your prompt" | python3 scripts/openrouter_gen.py <model>

Model format: openrouter/<provider>/<model> or just <provider>/<model>
Examples:
  openrouter/google/gemini-2.5-flash-lite
  openrouter/xiaomi/mimo-v2-pro
  openrouter/anthropic/claude-sonnet-4.6

Reads prompt from stdin, writes response to stdout.
OPENROUTER_API_KEY must be set.
"""

import json
import os
import sys
import urllib.error
import urllib.request

def _load_dotenv() -> None:
    """
    Load .env from project root, stripping surrounding quotes from values.
    Also cleans up any already-set env vars that bash exported with literal quotes
    (e.g. OPENROUTER_API_KEY="sk-or-..." → sk-or-...).
    """
    # First, strip quotes from any already-set env vars (bash export artifact)
    for key in ("OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(key, "")
        clean = val.strip().strip('"').strip("'")
        if clean and clean != val:
            os.environ[key] = clean

    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not os.environ.get(key):  # don't override if already cleanly set
                os.environ[key] = val


def main() -> None:
    _load_dotenv()

    raw_model = sys.argv[1] if len(sys.argv) > 1 else "google/gemini-2.5-flash-lite"
    # Strip leading "openrouter/" prefix — the API uses provider/model directly
    model = raw_model[len("openrouter/"):] if raw_model.startswith("openrouter/") else raw_model

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    prompt = sys.stdin.read()
    if not prompt.strip():
        print("ERROR: empty prompt on stdin", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} from OpenRouter: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        print(f"Unexpected API response: {exc}\n{data}", file=sys.stderr)
        sys.exit(1)

    print(content, end="")


if __name__ == "__main__":
    main()
