#!/usr/bin/env python3
"""
version_backup.py — Versioned backup rotation for generated sites.

Commands:
  rotate       --slug <slug>   Back up sites/<slug>/ → sites/<slug>_v1  (max 4 versions)
  parse-params --slug <slug>   Parse original build params from build.log (shell-eval output)
  list         --slug <slug>   List existing backup versions with timestamps

Rotation strategy (_v1 = newest, _v4 = oldest, max 4 kept):
  Before: slug/  _v1  _v2  _v3  _v4(full)
  Step 1: delete _v4
  Step 2: shift _v3→_v4  _v2→_v3  _v1→_v2
  Step 3: move slug/ → _v1
  Result: _v1(fresh backup)  _v2  _v3  _v4
"""

import argparse
import os
import re
import shutil
import sys
from datetime import datetime

MAX_VERSIONS = 4
SITES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sites")


def _version_path(slug: str, v: int) -> str:
    return os.path.join(SITES_DIR, f"{slug}_v{v}")


def cmd_rotate(slug: str) -> int:
    current = os.path.join(SITES_DIR, slug)
    if not os.path.isdir(current):
        print(f"ERROR: sites/{slug}/ does not exist — nothing to back up", file=sys.stderr)
        return 1

    # Delete oldest if full
    oldest = _version_path(slug, MAX_VERSIONS)
    if os.path.isdir(oldest):
        shutil.rmtree(oldest)
        print(f"🗑  Deleted oldest backup: {slug}_v{MAX_VERSIONS}")

    # Shift v(n-1) → v(n), from high to low
    for v in range(MAX_VERSIONS, 1, -1):
        src = _version_path(slug, v - 1)
        dst = _version_path(slug, v)
        if os.path.isdir(src):
            os.rename(src, dst)
            print(f"📦 Shifted: {slug}_v{v-1} → {slug}_v{v}")

    # Move current → _v1
    v1 = _version_path(slug, 1)
    os.rename(current, v1)
    print(f"✅ Backed up: sites/{slug}/ → sites/{slug}_v1")
    return 0


def cmd_parse_params(slug: str) -> int:
    """
    Read build.log from sites/<slug>_v1/ (newest backup, rotated just before this call)
    and output shell-eval-ready variables: BUSINESS_NAME, NICHE, ADDRESS, CONTACT
    """
    # Try _v1 first (just rotated), fall back to current if not yet rotated
    log_candidates = [
        os.path.join(SITES_DIR, f"{slug}_v1", "build.log"),
        os.path.join(SITES_DIR, slug, "build.log"),
    ]
    log_file = next((p for p in log_candidates if os.path.isfile(p)), None)
    if not log_file:
        print(f"ERROR: build.log not found for slug '{slug}'", file=sys.stderr)
        return 1

    with open(log_file, encoding="utf-8", errors="replace") as f:
        content = f.read()

    patterns = {
        "BUSINESS_NAME": r"Business:\s+(.+)",
        "NICHE":         r"Niche:\s+(.+)",
        "ADDRESS":       r"Address:\s+(.+)",
        "CONTACT":       r"Contact:\s+(.+)",
    }

    results = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, content)
        if m:
            results[key] = m.group(1).strip()
        else:
            print(f"ERROR: could not parse '{key}' from build.log", file=sys.stderr)
            return 1

    for key, value in results.items():
        # Shell-safe: wrap in single quotes, escape any internal single quotes
        safe = value.replace("'", "'\\''")
        print(f"{key}='{safe}'")

    return 0


def cmd_list(slug: str) -> int:
    current = os.path.join(SITES_DIR, slug)
    found = False

    if os.path.isdir(current):
        mtime = datetime.fromtimestamp(os.path.getmtime(current)).strftime("%Y-%m-%d %H:%M")
        print(f"  [current]  sites/{slug}/  ({mtime})")
        found = True

    for v in range(1, MAX_VERSIONS + 1):
        path = _version_path(slug, v)
        if os.path.isdir(path):
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            print(f"  [v{v}]       sites/{slug}_v{v}/  ({mtime})")
            found = True

    if not found:
        print(f"No site or backups found for slug: {slug}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Versioned site backup utility")
    sub = parser.add_subparsers(dest="command", required=True)

    for cmd in ("rotate", "parse-params", "list"):
        p = sub.add_parser(cmd)
        p.add_argument("--slug", required=True, help="Site slug (folder name under sites/)")

    args = parser.parse_args()

    if args.command == "rotate":
        sys.exit(cmd_rotate(args.slug))
    elif args.command == "parse-params":
        sys.exit(cmd_parse_params(args.slug))
    elif args.command == "list":
        sys.exit(cmd_list(args.slug))


if __name__ == "__main__":
    main()
