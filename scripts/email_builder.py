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


def _load_scrape_data(scrape_domain: str) -> Optional[dict]:
    """Load data.json from scrapes/<domain>/data.json if it exists."""
    root = Path(__file__).resolve().parent.parent
    path = root / "scrapes" / scrape_domain / "data.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


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
) -> str:
    """
    Render the HTML email for the given template number (1, 2, or 3).

    Returns the rendered HTML string.
    Raises ValueError for unknown template numbers.
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template}. Choose 1, 2, or 3.")

    template_path = TEMPLATES[template]
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    scraped = _load_scrape_data(scrape_domain) if scrape_domain else None
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
