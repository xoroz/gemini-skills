#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
TexNGo — Short ID Manager
==========================
Manages the mapping between short IDs (e.g. 00A) and site slugs.

Registry lives at sites/site-id.json:
[
  {
    "id": "00A",
    "business_name": "Marble Nails di Bertola Giada",
    "slug": "marble-nails-di-bertola-giada",
    "url": "http://dev.texngo.it/marble-nails-di-bertola-giada/index.html",
    "url_id": "http://dev.texngo.it/00A.html"
  }
]

Usage:
    # Auto-allocate next available ID for a business:
    uv run scripts/id_manager.py allocate --business "Marble Nails" --remote-url http://dev.texngo.it

    # Assign a specific ID:
    uv run scripts/id_manager.py assign --id 05A --business "Marble Nails" --remote-url http://dev.texngo.it

    # Lookup by slug:
    uv run scripts/id_manager.py lookup --slug marble-nails

    # Lookup by ID:
    uv run scripts/id_manager.py lookup --id 00A

Output (on success): prints key=value pairs to stdout for bash eval:
    SITE_ID=00A
    URLID=http://dev.texngo.it/00A.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
REGISTRY_FILE = PROJECT_DIR / "sites" / "site-id.json"


# ---------------------------------------------------------------------------
# ID arithmetic: 00A → 00B → ... → 00Z → 01A → ... → 99Z
# ---------------------------------------------------------------------------

def _id_to_int(site_id: str) -> int:
    """Convert a short ID like '05A' to a sortable integer (0-2599)."""
    num = int(site_id[:2])
    letter = ord(site_id[2].upper()) - ord("A")  # 0-25
    return num * 26 + letter


def _int_to_id(n: int) -> str:
    """Convert integer (0-2599) back to a short ID like '05A'."""
    num = n // 26
    letter = chr(ord("A") + n % 26)
    return f"{num:02d}{letter}"


def _next_id(existing_ids: list[str]) -> str:
    """Return the next available short ID after the highest existing one."""
    if not existing_ids:
        return "00A"
    highest = max(_id_to_int(i) for i in existing_ids)
    next_val = highest + 1
    if next_val > 2599:
        print("❌ Error: All 2600 short IDs (00A–99Z) are exhausted.", file=sys.stderr)
        sys.exit(1)
    return _int_to_id(next_val)


def _slugify(name: str) -> str:
    """Mirror create.sh slug logic: lowercase, spaces→hyphens, strip non-alnum."""
    s = name.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []
    try:
        data = json.loads(REGISTRY_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(entries: list[dict]) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def allocate(business_name: str, remote_url: str) -> dict:
    """Auto-assign the next available ID to a business."""
    registry = _load_registry()
    slug = _slugify(business_name)

    # Check if this slug already has an ID
    for entry in registry:
        if entry.get("slug") == slug:
            # Already assigned — return existing
            _print_result(entry)
            return entry

    existing_ids = [e["id"] for e in registry if "id" in e]
    new_id = _next_id(existing_ids)

    return _assign(new_id, business_name, slug, remote_url, registry)


def assign(site_id: str, business_name: str, remote_url: str) -> dict:
    """Assign a specific ID to a business."""
    registry = _load_registry()
    slug = _slugify(business_name)

    # Validate ID format
    if not re.match(r"^\d{2}[A-Z]$", site_id.upper()):
        print(f"❌ Error: Invalid ID format '{site_id}'. Must be NNL (e.g. 00A, 13B).", file=sys.stderr)
        sys.exit(1)

    site_id = site_id.upper()

    # Check if ID already taken by a DIFFERENT slug
    for entry in registry:
        if entry.get("id") == site_id:
            if entry.get("slug") == slug:
                # Same business → just return existing
                _print_result(entry)
                return entry
            else:
                print(
                    f"❌ Error: ID '{site_id}' is already assigned to '{entry.get('business_name', '?')}' "
                    f"(slug: {entry.get('slug', '?')}). Use a different ID.",
                    file=sys.stderr,
                )
                sys.exit(1)

    return _assign(site_id, business_name, slug, remote_url, registry)


def _assign(site_id: str, business_name: str, slug: str, remote_url: str, registry: list[dict]) -> dict:
    """Write a new entry and save."""
    remote_url = remote_url.rstrip("/")
    entry = {
        "id": site_id,
        "business_name": business_name,
        "slug": slug,
        "url": f"{remote_url}/{slug}/index.html" if remote_url else f"{slug}/index.html",
        "url_id": f"{remote_url}/{site_id}.html" if remote_url else f"{site_id}.html",
    }

    registry.append(entry)
    _save_registry(registry)
    _print_result(entry)
    return entry


def lookup(site_id: str | None = None, slug: str | None = None) -> dict | None:
    """Find an entry by ID or slug."""
    registry = _load_registry()
    for entry in registry:
        if site_id and entry.get("id", "").upper() == site_id.upper():
            _print_result(entry)
            return entry
        if slug and entry.get("slug") == slug:
            _print_result(entry)
            return entry
    print("NOT_FOUND", file=sys.stderr)
    sys.exit(1)


def _print_result(entry: dict) -> None:
    """Output key=value pairs for shell eval."""
    print(f"SITE_ID={entry['id']}")
    print(f"URLID={entry.get('url_id', '')}")
    print(f"URL={entry.get('url', '')}")
    print(f"SLUG={entry.get('slug', '')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="TexNGo Short ID Manager")
    sub = ap.add_subparsers(dest="action", required=True)

    # -- allocate --
    p_alloc = sub.add_parser("allocate", help="Auto-allocate next available ID")
    p_alloc.add_argument("--business", required=True, help="Business name")
    p_alloc.add_argument("--remote-url", default="", help="Remote site base URL")

    # -- assign --
    p_assign = sub.add_parser("assign", help="Assign a specific ID")
    p_assign.add_argument("--id", required=True, help="Short ID to assign (e.g. 05A)")
    p_assign.add_argument("--business", required=True, help="Business name")
    p_assign.add_argument("--remote-url", default="", help="Remote site base URL")

    # -- lookup --
    p_lookup = sub.add_parser("lookup", help="Lookup by ID or slug")
    p_lookup.add_argument("--id", default=None, help="Short ID to find")
    p_lookup.add_argument("--slug", default=None, help="Site slug to find")

    args = ap.parse_args()

    if args.action == "allocate":
        allocate(args.business, args.remote_url)
    elif args.action == "assign":
        assign(args.id, args.business, args.remote_url)
    elif args.action == "lookup":
        if not args.id and not args.slug:
            print("❌ Provide --id or --slug", file=sys.stderr)
            sys.exit(1)
        lookup(site_id=args.id, slug=args.slug)


if __name__ == "__main__":
    main()
