#!/usr/bin/env python3
"""
Email builder for TexNGo site-delivery campaigns.

Renders one of three HTML email templates with business-specific data
scraped from data.json and/or supplied as arguments.

Templates (assets/emails/):
  1 = template_sorpresa.html  — dark hero, warm reveal
  2 = template_offerta.html   — white premium, feature bullets
  3 = template_diretto.html   — ultra-minimal, pure punch

Variables substituted (Python string.Template ${var} syntax):
  business_name   — "Arte Ottica"
  niche_label     — "ottica e occhiali"
  site_url        — "https://texngo.it/00A.html"
  primary_color   — "#42464e"  (falls back to #f97316)
  address_line    — "Via Giovan Pietro, 2A — 54033 Carrara MS"

Usage:
  from scripts.email_builder import render_email, TEMPLATE_SUBJECTS

  html = render_email(
      template=1,
      business_name="Arte Ottica",
      niche_label="ottica",
      site_url="https://texngo.it/00A.html",
      primary_color="#42464e",
      address_line="Via Roma 1, Carrara",
  )
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from string import Template
from typing import Optional

# ---------------------------------------------------------------------------
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "emails"

TEMPLATES = {
    1: TEMPLATE_DIR / "template_sorpresa.html",
    2: TEMPLATE_DIR / "template_offerta.html",
    3: TEMPLATE_DIR / "template_diretto.html",
}

TEMPLATE_SUBJECTS = {
    1: "Ciao ${business_name} — ti abbiamo fatto una sorpresa 🎁",
    2: "${business_name} — accesso esclusivo riservato per te ⏳",
    3: "${business_name} — il tuo sito web è online",
}

DEFAULT_PRIMARY = "#f97316"
DEFAULT_SECONDARY = "#1e293b"

# ---------------------------------------------------------------------------


_SCRAPES_ROOT = Path(__file__).resolve().parent.parent / "scrapes"


def _load_scrape_data(scrape_domain: str) -> Optional[dict]:
    """Load data.json from scrapes/<domain>/data.json if it exists."""
    path = _SCRAPES_ROOT / scrape_domain / "data.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _find_scrape_data(slug: str, business_name: str) -> Optional[dict]:
    """
    Auto-discover scraped data for a site when no explicit domain is known.

    Scans all scrapes/*/data.json files and returns the best match based on:
      1. slug appears in the scraped site_url hostname
      2. business_name appears in metadata.title (case-insensitive)

    Returns the data dict, or None if nothing matches.
    """
    if not _SCRAPES_ROOT.exists():
        return None

    slug_clean       = slug.replace("-", "").lower()
    biz_clean        = re.sub(r"[^a-z0-9]", "", business_name.lower())
    best: Optional[dict] = None

    for data_path in sorted(_SCRAPES_ROOT.glob("*/data.json")):
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        site_url = data.get("site_url", "")
        title    = data.get("metadata", {}).get("title", "")

        host_clean  = re.sub(r"[^a-z0-9]", "", site_url.lower())
        title_clean = re.sub(r"[^a-z0-9]", "", title.lower())

        # Slug match is strongest signal
        if slug_clean and slug_clean in host_clean:
            return data  # immediate hit

        # Business name match is good enough
        if biz_clean and len(biz_clean) >= 4 and biz_clean in title_clean:
            best = data   # keep scanning for a slug hit

    return best


def _pick_primary_color(scraped: Optional[dict], override: str = "") -> str:
    """Return the best primary brand color from scraped data or override."""
    if override and override.startswith("#"):
        return override
    if scraped:
        primary = scraped.get("branding", {}).get("color_palette", {}).get("primary", [])
        if primary:
            return primary[0]
    return DEFAULT_PRIMARY


def _pick_address(scraped: Optional[dict], override: str = "") -> str:
    if override:
        return override
    if scraped:
        addr = scraped.get("contact_info", {}).get("physical_address", "")
        if addr:
            # Collapse newlines to em-dash separated line
            return re.sub(r"\s*\n\s*", " — ", addr.strip())
    return ""


def render_email(
    template: int,
    business_name: str,
    niche_label: str,
    site_url: str,
    primary_color: str = "",
    address_line: str = "",
    scrape_domain: str = "",
    slug: str = "",
) -> str:
    """
    Render the HTML email for the given template number (1, 2, or 3).

    Scraped data is loaded automatically:
      - If scrape_domain is given → load scrapes/<scrape_domain>/data.json directly.
      - Otherwise → scan all scrapes/*/data.json and pick the best match for
        slug / business_name. Covers the common case where the site was built
        with --website and the scrape cache already exists.

    Returns the rendered HTML string.
    Raises ValueError for unknown template numbers.
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template}. Choose 1, 2, or 3.")

    template_path = TEMPLATES[template]
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    if scrape_domain:
        scraped = _load_scrape_data(scrape_domain)
    else:
        scraped = _find_scrape_data(slug, business_name)

    color   = _pick_primary_color(scraped, primary_color)
    address = _pick_address(scraped, address_line)

    raw_html = template_path.read_text(encoding="utf-8")

    # Render — use safe_substitute so missing vars don't raise
    result = Template(raw_html).safe_substitute(
        business_name=business_name,
        niche_label=niche_label,
        site_url=site_url,
        primary_color=color,
        address_line=address or f"Attività locale — {niche_label}",
    )
    return result


def render_subject(template: int, business_name: str) -> str:
    """Render the email subject line for the given template."""
    tpl = TEMPLATE_SUBJECTS.get(template, TEMPLATE_SUBJECTS[1])
    return Template(tpl).safe_substitute(business_name=business_name)
