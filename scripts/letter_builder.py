#!/usr/bin/env python3
"""
Letter builder for TexNGo physical mail campaigns.

Renders an HTML letter template with business-specific data,
parses Italian addresses into structured fields for the OpenAPI
Ufficio Postale API, and sends letters via Posta Ordinaria.

API: POST https://ws.ufficiopostale.com/ordinarie/
Docs: https://console.openapi.com/apis/ufficiopostale/documentation

Usage (as module):
    from scripts.letter_builder import render_letter, build_payload, send_letter

    html = render_letter(
        business_name="Arte Ottica",
        niche_label="ottica",
        site_url="https://dev.texngo.it/00A.html",
    )

    payload = build_payload(
        sender=default_sender(),
        recipient_name="Mario Rossi",
        recipient_company="Arte Ottica",
        recipient_address="Via Roma 1, 00100 Roma RM",
        html_document=html,
        color=False,
        autoconfirm=False,
    )

    result = send_letter(payload, api_token="...", dry_run=True)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "letters"
LETTER_TEMPLATE = TEMPLATE_DIR / "template_lettera.html"

API_BASE_URL = "https://ws.ufficiopostale.com"
API_TEST_URL = "https://test.ws.ufficiopostale.com"

# ---------------------------------------------------------------------------
# Italian address DUG (denominazione urbanistica generica) and Province lookups
# ---------------------------------------------------------------------------
_ITALIAN_PROVINCES = {
    'AG', 'AL', 'AN', 'AO', 'AP', 'AQ', 'AR', 'AT', 'AV', 'BA', 'BG', 'BI', 'BL', 'BN', 'BO', 
    'BR', 'BS', 'BT', 'BZ', 'CA', 'CB', 'CE', 'CH', 'CI', 'CL', 'CN', 'CO', 'CR', 'CS', 'CT', 
    'CZ', 'EN', 'FC', 'FE', 'FG', 'FI', 'FM', 'FR', 'GE', 'GO', 'GR', 'IM', 'IS', 'KR', 'LC', 
    'LE', 'LI', 'LO', 'LT', 'LU', 'MB', 'MC', 'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NA', 'NO', 
    'NU', 'OG', 'OR', 'PA', 'PC', 'PD', 'PE', 'PG', 'PI', 'PN', 'PO', 'PR', 'PT', 'PU', 'PV', 
    'PZ', 'RA', 'RC', 'RE', 'RG', 'RI', 'RM', 'RN', 'RO', 'SA', 'SI', 'SO', 'SP', 'SR', 'SS', 
    'SV', 'TA', 'TE', 'TN', 'TO', 'TP', 'TR', 'TS', 'TV', 'UD', 'VA', 'VB', 'VC', 'VE', 'VI', 
    'VR', 'VS', 'VT', 'VV'
}

_DUG_MAP = {
    "via": "Via",
    "viale": "Viale",
    "piazza": "Piazza",
    "piazzale": "Piazzale",
    "corso": "Corso",
    "vicolo": "Vicolo",
    "largo": "Largo",
    "vico": "Vico",
    "strada": "Strada",
    "contrada": "Contrada",
    "salita": "Salita",
    "traversa": "Traversa",
    "lungomare": "Lungomare",
    "lungotevere": "Lungotevere",
    "lungadige": "Lungadige",
    "lungarno": "Lungarno",
    "loc.": "Località",
    "localita": "Località",
    "località": "Località",
    "borgata": "Borgata",
    "borgo": "Borgo",
    "rione": "Rione",
    "frazione": "Frazione",
    "regione": "Regione",
    "ss": "Strada Statale",
    "sp": "Strada Provinciale",
    "ruga": "Ruga",
    "calle": "Calle",
    "fondamenta": "Fondamenta",
    "salizzada": "Salizzada",
    "campiello": "Campiello",
    "sestiere": "Sestiere",
    "contrà": "Contrada",
    "vicoletto": "Vicoletto",
    "viazza": "Viazza",
}


def parse_address(raw: str) -> dict:
    """
    Parse a free-form Italian address into structured API fields.

    Accepts formats like:
        "Via Roma 1, 00100 Roma RM"
        "Piazza San Giovanni, 6, 00101 Roma RE"
        "Via Dante Alighieri 12/A — 54033 Carrara MS"

    Returns dict with keys: dug, indirizzo, civico, cap, comune, provincia.
    Missing fields are empty strings (the API will reject if required ones are missing).
    """
    # Normalize separators
    addr = raw.strip()
    addr = addr.replace("—", ",").replace("–", ",").replace(" - ", ", ")

    result = {
        "dug": "",
        "indirizzo": "",
        "civico": "",
        "cap": "",
        "comune": "",
        "provincia": "",
    }

    # 1. Extract Provincia (last matching 2 uppercase letters in the valid provinces list)
    provs = list(re.finditer(r"\b([A-Z]{2})\b", addr))
    for match in reversed(provs):
        if match.group(1) in _ITALIAN_PROVINCES:
            result["provincia"] = match.group(1)
            # Remove the province from the string to avoid confusing comune extraction
            addr = addr[:match.start()] + addr[match.end():]
            break

    addr = addr.strip().rstrip(",").strip()

    # 2. Extract CAP (5 digits)
    cap_match = re.search(r"\b(\d{5})\b", addr)
    if cap_match:
        result["cap"] = cap_match.group(1)
        before_cap = addr[:cap_match.start()].strip().rstrip(",").strip()
        after_cap = addr[cap_match.end():].strip().rstrip(",").strip()
        
        if after_cap:
            # Typical for "10100 Torino"
            result["comune"] = after_cap.strip()
            addr = before_cap
        else:
            # Typical for "Torino 10100"
            parts = [p.strip() for p in before_cap.split(",") if p.strip()]
            if len(parts) > 1:
                result["comune"] = parts[-1]
                addr = ", ".join(parts[:-1])
            else:
                addr = before_cap
    else:
        # No CAP found. Try extracting comune using the last comma fragment.
        parts = [p.strip() for p in addr.split(",") if p.strip()]
        if len(parts) > 1:
            result["comune"] = parts[-1]
            addr = ", ".join(parts[:-1])

    # Now addr should be something like "Via Roma 1" or "Via Dante Alighieri 12/A"
    # Try to split DUG from the rest
    parts = addr.split(None, 1)  # Split on first whitespace
    if parts:
        first_word = parts[0].lower().rstrip(".")
        if first_word in _DUG_MAP:
            result["dug"] = _DUG_MAP[first_word]
            remainder = parts[1] if len(parts) > 1 else ""
        else:
            # No recognized DUG, try two-word DUG like "Strada Statale"
            if len(parts) > 1:
                two_word = parts[0].lower() + " " + parts[1].split()[0].lower() if parts[1] else ""
                if two_word in _DUG_MAP:
                    result["dug"] = _DUG_MAP[two_word]
                    remainder = " ".join(parts[1].split()[1:])
                else:
                    remainder = addr
            else:
                remainder = addr

        # Extract civico (house number) — last number-like token
        remainder = remainder.strip().rstrip(",").strip()
        m_civico = re.search(r"[,\s]+(\d+[/]?\w*)\s*$", remainder)
        if m_civico:
            result["civico"] = m_civico.group(1)
            remainder = remainder[: m_civico.start()].strip().rstrip(",").strip()

        result["indirizzo"] = remainder.strip()

    return result


def validate_address(addr: dict) -> None:
    """
    Validates the parsed Italian address against Ufficio Postale API limits.
    Raises ValueError with a descriptive message if invalid.
    """
    if not addr["cap"] or not re.match(r"^\d{5}$", addr["cap"]):
        raise ValueError(f"CAP must be exactly 5 digits. Got: '{addr['cap']}'")

    if not addr["provincia"] or not re.match(r"^[A-Za-z]{2}$", addr["provincia"]):
        raise ValueError(f"Provincia must be exactly 2 letters. Got: '{addr['provincia']}'")

    if not addr["comune"]:
        raise ValueError("Comune (City) could not be parsed or is missing.")
    elif len(addr["comune"]) > 44:
        raise ValueError(f"Comune exceeds 44 characters (Length: {len(addr['comune'])}).")

    if not addr["indirizzo"]:
        raise ValueError("Indirizzo (Street address) could not be parsed or is missing.")
    
    # DUG + space + Indirizzo combined <= 44 chars (API limit for street)
    # The API combines them: e.g., "Via" + " " + "Roma"
    dug = addr.get("dug", "")
    full_street = f"{dug} {addr['indirizzo']}".strip()
    if len(full_street) > 44:
        # Auto-truncate to prevent 422
        allowed_indirizzo_len = 44 - len(dug) - 1
        addr["indirizzo"] = addr["indirizzo"][:allowed_indirizzo_len].strip()

    if addr.get("civico") and len(addr["civico"]) > 15:
        addr["civico"] = addr["civico"][:15]
        
    return None


def default_sender() -> dict:
    """
    Build the sender (mittente) dict from environment variables.
    Falls back to sensible defaults for TexNGo.
    """
    return {
        "nome": os.environ.get("LETTER_SENDER_NAME", "TexNGo"),
        "cognome": os.environ.get("LETTER_SENDER_COGNOME", "AI Agency"),
        "dug": os.environ.get("LETTER_SENDER_DUG", "Via"),
        "indirizzo": os.environ.get("LETTER_SENDER_ADDRESS", "del Tritone"),
        "civico": os.environ.get("LETTER_SENDER_CIVICO", "1"),
        "comune": os.environ.get("LETTER_SENDER_COMUNE", "Roma"),
        "cap": os.environ.get("LETTER_SENDER_CAP", "00187"),
        "provincia": os.environ.get("LETTER_SENDER_PROVINCIA", "RM"),
        "nazione": "Italia",
        "email": os.environ.get("LETTER_SENDER_EMAIL", "info@texngo.it"),
    }


def render_letter(
    business_name: str,
    niche_label: str,
    site_url: str,
    letter_date: str = "",
) -> str:
    """
    Render the HTML letter template with variable substitution.
    Returns the HTML string ready to be sent as the `documento` field.
    """
    if not LETTER_TEMPLATE.exists():
        raise FileNotFoundError(f"Letter template not found: {LETTER_TEMPLATE}")

    if not letter_date:
        letter_date = datetime.now().strftime("%d/%m/%Y")

    raw_html = LETTER_TEMPLATE.read_text(encoding="utf-8")

    result = Template(raw_html).safe_substitute(
        business_name=business_name,
        niche_label=niche_label,
        site_url=site_url,
        letter_date=letter_date,
    )
    return result


def build_payload(
    sender: dict,
    recipient_name: str,
    recipient_company: str,
    recipient_address: str,
    html_document: str,
    color: bool = False,
    autoconfirm: bool = False,
) -> dict:
    """
    Build the full JSON payload for POST /ordinarie/.

    Args:
        sender: Structured sender (mittente) dict
        recipient_name: Full name, e.g. "Mario Rossi"
        recipient_company: Company name (c/o field), e.g. "Arte Ottica SRL"
        recipient_address: Free-form address, e.g. "Via Roma 1, 00100 Roma RM"
        html_document: Rendered HTML letter content
        color: Print in color (costs more)
        autoconfirm: Send immediately without manual confirmation step
    """
    # The Ufficio Postale API limits the combination of nome + cognome to 44 characters.
    safe_name = recipient_name.strip()
    if len(safe_name) > 44:
        safe_name = safe_name[:44].strip()

    # Parse recipient name into nome/cognome
    name_parts = safe_name.split(None, 1)
    nome = name_parts[0] if name_parts else ""
    cognome = name_parts[1] if len(name_parts) > 1 else ""

    # Parse and validate address
    addr = parse_address(recipient_address)
    try:
        validate_address(addr)
    except ValueError as e:
        raise ValueError(f"Invalid recipient address: {e}")

    destinatario = {
        "nome": nome,
        "cognome": cognome,
        "dug": addr["dug"],
        "indirizzo": addr["indirizzo"],
        "civico": addr["civico"],
        "comune": addr["comune"],
        "cap": addr["cap"],
        "provincia": addr["provincia"],
        "nazione": "Italia",
    }
    if recipient_company:
        destinatario["co"] = recipient_company

    return {
        "mittente": sender,
        "destinatari": [destinatario],
        "documento": [html_document],
        "opzioni": {
            "fronteretro": False,
            "colori": color,
            "ar": False,
            "autoconfirm": autoconfirm,
        },
    }


def send_letter(
    payload: dict,
    api_token: str,
    dry_run: bool = False,
    test_mode: bool = False,
) -> dict:
    """
    Send the letter via the OpenAPI Ufficio Postale Posta Ordinaria API.

    Args:
        payload: Full request body (from build_payload)
        api_token: Bearer token for the API
        dry_run: If True, just return the payload without calling the API
        test_mode: Use the sandbox base URL (https://test.ws.ufficiopostale.com)

    Returns:
        API response dict (or the payload dict in dry_run mode)
    """
    if dry_run:
        return {"dry_run": True, "payload": payload}

    if httpx is None:
        raise ImportError("httpx is required: pip install httpx")

    if not api_token:
        raise ValueError("API token is required to send letters")

    base = API_TEST_URL if (test_mode or "_TEST" in api_token or len(api_token) < 30) else API_BASE_URL
    url = f"{base}/ordinarie/"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers=headers)

        # ── AUTO-RETRY per Frazioni (Errore 12027 Comune/Cap in conflitto) ──
        if response.status_code == 422:
            try:
                err_data = response.json()
                if err_data.get("error") == 12027:
                    old_comune = payload["destinatari"][0].get("comune", "")
                    fallback = ""
                    lower_comune = old_comune.lower()
                    if " di " in lower_comune:
                        # Extract everything after the LAST " di "
                        # e.g., "Marina di Carrara" -> "Carrara"
                        fallback = old_comune.rsplit(" di ", 1)[-1].strip()
                    elif " del " in lower_comune:
                        fallback = old_comune.rsplit(" del ", 1)[-1].strip()
                        
                    if fallback and len(fallback) > 2 and fallback.lower() != lower_comune:
                        payload["destinatari"][0]["comune"] = fallback
                        # Retry the request with the new Comune
                        response = client.post(url, json=payload, headers=headers)
            except Exception:
                pass

    result = {
        "status_code": response.status_code,
        "ok": response.status_code in (200, 201, 202),
    }

    try:
        result["data"] = response.json()
    except Exception:
        result["raw"] = response.text[:2000]

    return result


def get_letter_status(
    order_id: str,
    api_token: str,
    test_mode: bool = False,
) -> dict:
    """
    Retrieve the status and tracking details of a specific letter order.

    Args:
        order_id: The ID returned by POST /ordinarie/
        api_token: Bearer token for the API
        test_mode: Use the sandbox base URL
    """
    if httpx is None:
        raise ImportError("httpx is required: pip install httpx")

    if not api_token:
        raise ValueError("API token is required to check order status")

    base = API_TEST_URL if (test_mode or "_TEST" in api_token or len(api_token) < 30) else API_BASE_URL
    url = f"{base}/ordinarie/{order_id}"
    headers = {
        "Authorization": f"Bearer {api_token}",
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, headers=headers)

    result = {
        "status_code": response.status_code,
        "ok": response.status_code == 200,
    }

    try:
        result["data"] = response.json()
    except Exception:
        result["raw"] = response.text[:2000]

    return result
