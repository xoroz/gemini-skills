#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
TexNGo — Short ID Manager
==========================
Manages the mapping between short IDs (e.g. 00A) and site slugs.

Registry file is controlled by the SITE_ID_REGISTRY environment variable:
  - Default (production):  sites/site-id.json
  - DEV / test override:   SITE_ID_REGISTRY=sites/site-id-dev.json

This allows DEV and PROD to use separate registries so test builds
never pollute production IDs.

Registry format (JSON array):
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
    # Auto-allocate next available ID:
    uv run scripts/id_manager.py allocate --business "Marble Nails" --remote-url http://dev.texngo.it

    # Assign a specific ID:
    uv run scripts/id_manager.py assign --id 05A --business "Marble Nails" --remote-url http://dev.texngo.it

    # Lookup by ID or slug:
    uv run scripts/id_manager.py lookup --id 00A
    uv run scripts/id_manager.py lookup --slug marble-nails

    # Free an ID (remove from registry):
    uv run scripts/id_manager.py unassign --id 00A
    uv run scripts/id_manager.py unassign --slug marble-nails

    # Update the URL for an existing entry (e.g. DEV → PROD promotion):
    uv run scripts/id_manager.py update --id 00A --remote-url https://texngo.it
    uv run scripts/id_manager.py update --slug marble-nails --remote-url https://texngo.it

    # List all entries:
    uv run scripts/id_manager.py list

Output (on success for allocate/assign/lookup/update): prints key=value pairs to stdout:
    SITE_ID=00A
    URLID=http://dev.texngo.it/00A.html
    URL=http://dev.texngo.it/marble-nails-di-bertola-giada/index.html
    SLUG=marble-nails-di-bertola-giada
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_DIR  = SCRIPT_DIR.parent

# ── Registry path ─────────────────────────────────────────────────────────────
# Override via SITE_ID_REGISTRY env var to isolate DEV from PROD:
#   SITE_ID_REGISTRY=sites/site-id-dev.json MODE=DEV ./create.sh ...
_registry_env = os.environ.get("SITE_ID_REGISTRY", "")
REGISTRY_FILE = (
    PROJECT_DIR / _registry_env
    if _registry_env
    else PROJECT_DIR / "sites" / "site-id.json"
)


# ---------------------------------------------------------------------------
# ID arithmetic: 00A → 00B → ... → 00Z → 01A → ... → 99Z
# ---------------------------------------------------------------------------

def _id_to_int(site_id: str) -> int:
    """Convert a short ID like '05A' to a sortable integer (0-2599)."""
    num    = int(site_id[:2])
    letter = ord(site_id[2].upper()) - ord("A")  # 0-25
    return num * 26 + letter


def _int_to_id(n: int) -> str:
    """Convert integer (0-2599) back to a short ID like '05A'."""
    num    = n // 26
    letter = chr(ord("A") + n % 26)
    return f"{num:02d}{letter}"


def _next_id(existing_ids: list[str]) -> str:
    """Return the next available short ID after the highest existing one."""
    if not existing_ids:
        return "00A"
    highest  = max(_id_to_int(i) for i in existing_ids)
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
    """Auto-assign the next available ID to a business (idempotent)."""
    registry = _load_registry()
    slug     = _slugify(business_name)

    # Already assigned → return existing (idempotent)
    for entry in registry:
        if entry.get("slug") == slug:
            _print_result(entry)
            return entry

    existing_ids = [e["id"] for e in registry if "id" in e]
    new_id = _next_id(existing_ids)
    return _assign_write(new_id, business_name, slug, remote_url, registry)


def assign(site_id: str, business_name: str, remote_url: str) -> dict:
    """Assign a specific ID to a business (idempotent for same slug)."""
    registry = _load_registry()
    slug     = _slugify(business_name)

    # Validate format
    if not re.match(r"^\d{2}[A-Z]$", site_id.upper()):
        print(f"❌ Error: Invalid ID format '{site_id}'. Must be NNL (e.g. 00A, 13B).", file=sys.stderr)
        sys.exit(1)

    site_id = site_id.upper()

    # Check for collision
    for entry in registry:
        if entry.get("id") == site_id:
            if entry.get("slug") == slug:
                _print_result(entry)
                return entry
            else:
                print(
                    f"❌ Error: ID '{site_id}' is already assigned to "
                    f"'{entry.get('business_name', '?')}' (slug: {entry.get('slug', '?')}). "
                    "Use a different ID or unassign it first.",
                    file=sys.stderr,
                )
                sys.exit(1)

    return _assign_write(site_id, business_name, slug, remote_url, registry)


def _assign_write(site_id: str, business_name: str, slug: str, remote_url: str, registry: list[dict]) -> dict:
    """Write a new entry and save."""
    remote_url = remote_url.rstrip("/")
    entry = {
        "id":            site_id,
        "business_name": business_name,
        "slug":          slug,
        "url":           f"{remote_url}/{slug}/index.html" if remote_url else f"{slug}/index.html",
        "url_id":        f"{remote_url}/{site_id}.html"    if remote_url else f"{site_id}.html",
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


def unassign(site_id: str | None = None, slug: str | None = None) -> None:
    """Remove an entry from the registry, freeing the ID for re-use."""
    registry = _load_registry()

    to_remove = None
    for entry in registry:
        if site_id and entry.get("id", "").upper() == site_id.upper():
            to_remove = entry
            break
        if slug and entry.get("slug") == slug:
            to_remove = entry
            break

    if to_remove is None:
        print("❌ Error: Entry not found — nothing was changed.", file=sys.stderr)
        sys.exit(1)

    registry.remove(to_remove)
    _save_registry(registry)
    print(f"✅ Unassigned: ID={to_remove['id']}  slug={to_remove['slug']}")
    print(f"   The ID '{to_remove['id']}' is now free and will be re-used by the next allocate.")
    print(f"   Registry: {REGISTRY_FILE}")


def update(remote_url: str, site_id: str | None = None, slug: str | None = None) -> dict:
    """Update the URL and url_id for an existing entry (e.g. DEV → PROD promotion)."""
    registry = _load_registry()
    remote_url = remote_url.rstrip("/")

    target = None
    for entry in registry:
        if site_id and entry.get("id", "").upper() == site_id.upper():
            target = entry
            break
        if slug and entry.get("slug") == slug:
            target = entry
            break

    if target is None:
        print("❌ Error: Entry not found — nothing was changed.", file=sys.stderr)
        sys.exit(1)

    old_url    = target.get("url", "")
    old_url_id = target.get("url_id", "")

    target["url"]    = f"{remote_url}/{target['slug']}/index.html"
    target["url_id"] = f"{remote_url}/{target['id']}.html"

    _save_registry(registry)

    print(f"✅ Updated entry: ID={target['id']}  slug={target['slug']}")
    print(f"   url    : {old_url}  →  {target['url']}")
    print(f"   url_id : {old_url_id}  →  {target['url_id']}")
    print(f"   ⚠️  Remember to regenerate the flyer so the QR code reflects the new URL.")
    _print_result(target)
    return target


def list_all() -> None:
    """Print a human-readable table of all registry entries."""
    registry = _load_registry()
    if not registry:
        print(f"Registry is empty: {REGISTRY_FILE}")
        return

    print(f"\n📋 Site ID Registry: {REGISTRY_FILE}")
    print(f"   {len(registry)} entries\n")
    col_id   = max(4,  max(len(e.get("id",   "")) for e in registry))
    col_slug = max(4,  max(len(e.get("slug", "")) for e in registry))
    col_biz  = max(13, max(len(e.get("business_name", "")) for e in registry))
    header   = f"  {'ID':<{col_id}}  {'SLUG':<{col_slug}}  {'BUSINESS':<{col_biz}}  URL_ID"
    print(header)
    print("  " + "─" * (len(header) + 10))
    for e in sorted(registry, key=lambda x: _id_to_int(x.get("id", "00A"))):
        print(f"  {e.get('id','?'):<{col_id}}  {e.get('slug','?'):<{col_slug}}  {e.get('business_name','?'):<{col_biz}}  {e.get('url_id','')}")
    print()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

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
    ap  = argparse.ArgumentParser(
        description="TexNGo Short ID Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Registry file: controlled by SITE_ID_REGISTRY env var (default: sites/site-id.json)
  DEV example:  SITE_ID_REGISTRY=sites/site-id-dev.json uv run scripts/id_manager.py ...
""",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    # -- allocate --
    p_alloc = sub.add_parser("allocate", help="Auto-allocate next available ID for a business")
    p_alloc.add_argument("--business",   required=True, help="Business name")
    p_alloc.add_argument("--remote-url", default="",    help="Remote site base URL")

    # -- assign --
    p_assign = sub.add_parser("assign",  help="Assign a specific ID to a business")
    p_assign.add_argument("--id",        required=True, help="Short ID to assign (e.g. 05A)")
    p_assign.add_argument("--business",  required=True, help="Business name")
    p_assign.add_argument("--remote-url",default="",    help="Remote site base URL")

    # -- lookup --
    p_lookup = sub.add_parser("lookup",  help="Look up an entry by ID or slug")
    p_lookup.add_argument("--id",   default=None, help="Short ID to find (e.g. 00A)")
    p_lookup.add_argument("--slug", default=None, help="Site slug to find")

    # -- unassign --
    p_unassign = sub.add_parser("unassign", help="Free an ID — remove its entry from the registry")
    p_unassign.add_argument("--id",   default=None, help="Short ID to remove (e.g. 00A)")
    p_unassign.add_argument("--slug", default=None, help="Site slug to remove")

    # -- update --
    p_update = sub.add_parser("update", help="Update URL for an existing entry (e.g. DEV → PROD)")
    p_update.add_argument("--id",        default=None,  help="Short ID of the entry to update")
    p_update.add_argument("--slug",      default=None,  help="Slug of the entry to update")
    p_update.add_argument("--remote-url",required=True, help="New base URL (e.g. https://texngo.it)")

    # -- list --
    sub.add_parser("list", help="List all registry entries in a readable table")

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

    elif args.action == "unassign":
        if not args.id and not args.slug:
            print("❌ Provide --id or --slug", file=sys.stderr)
            sys.exit(1)
        unassign(site_id=args.id, slug=args.slug)

    elif args.action == "update":
        if not args.id and not args.slug:
            print("❌ Provide --id or --slug", file=sys.stderr)
            sys.exit(1)
        update(args.remote_url, site_id=args.id, slug=args.slug)

    elif args.action == "list":
        list_all()


if __name__ == "__main__":
    main()
