#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
CLI tool to send physical marketing letters via OpenAPI Ufficio Postale.

Uses Posta Ordinaria (POST /ordinarie/) to deliver printed letters
with the same formal Italian marketing tone as the TexNGo email campaigns.

Usage:
    # Dry run — prints JSON payload, no API call, zero cost:
    uv run scripts/letter_sender.py \
        --business-name "Arte Ottica" \
        --niche "ottica" \
        --site-url "https://dev.texngo.it/00A.html" \
        --recipient-name "Mario Rossi" \
        --recipient-address "Via Roma 1, 00100 Roma RM" \
        --dry-run

    # Actually send (requires OPENAPI_POST in .env):
    uv run scripts/letter_sender.py \
        --business-name "Arte Ottica" \
        --niche "ottica" \
        --site-url "https://dev.texngo.it/00A.html" \
        --recipient-name "Mario Rossi" \
        --recipient-address "Via Roma 1, 00100 Roma RM" \
        --send

Environment variables:
    OPENAPI_POST            — API token (required for --send)
    LETTER_SENDER_NAME      — Sender first name (default: TexNGo)
    LETTER_SENDER_COGNOME   — Sender last name  (default: AI Agency)
    LETTER_SENDER_ADDRESS   — Sender street name
    LETTER_SENDER_CIVICO    — Sender street number
    LETTER_SENDER_CAP       — Sender postal code
    LETTER_SENDER_COMUNE    — Sender city
    LETTER_SENDER_PROVINCIA — Sender province (2-letter code)
"""

import argparse
import json
import os
import sys

# ── Load .env (same logic as main.py) ─────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ── Import the builder module ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from letter_builder import (  # noqa: E402
    build_payload,
    default_sender,
    parse_address,
    render_letter,
    send_letter,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send physical marketing letters via OpenAPI Ufficio Postale (Posta Ordinaria)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument("--business-name", required=True, help="Business name (e.g. 'Arte Ottica')")
    parser.add_argument("--niche", required=True, help="Business niche label (e.g. 'ottica')")
    parser.add_argument("--site-url", required=True, help="Preview site URL (e.g. 'https://dev.texngo.it/00A.html')")
    parser.add_argument("--recipient-name", required=True, help="Recipient full name (e.g. 'Mario Rossi')")
    parser.add_argument("--recipient-address", required=True, help="Full address (e.g. 'Via Roma 1, 00100 Roma RM')")

    # Optional
    parser.add_argument("--recipient-company", default="", help="Company name for c/o field")
    parser.add_argument("--color", action="store_true", help="Print in color (costs more)")
    parser.add_argument("--autoconfirm", action="store_true", help="Auto-confirm sending (skip manual review)")
    parser.add_argument("--letter-date", default="", help="Override letter date (DD/MM/YYYY)")

    # Mode
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Print payload JSON only (default)")
    mode.add_argument("--send", action="store_true", help="Actually send the letter via API")

    # Options
    parser.add_argument("--test-mode", action="store_true", help="Use sandbox base URL (test.ws.ufficiopostale.com)")
    parser.add_argument("--show-html", action="store_true", help="Print rendered HTML to stdout")
    parser.add_argument("--show-address", action="store_true", help="Show parsed address fields and exit")

    args = parser.parse_args()

    # ── Address parsing debug mode ────────────────────────────────────────────
    if args.show_address:
        parsed = parse_address(args.recipient_address)
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return 0

    # ── Render the letter HTML ────────────────────────────────────────────────
    print(f"📝 Rendering letter for: {args.business_name}")
    html = render_letter(
        business_name=args.business_name,
        niche_label=args.niche,
        site_url=args.site_url,
        letter_date=args.letter_date,
    )

    # Archive the rendered letter
    import re as _re
    safe_name = _re.sub(r"[^a-z0-9]", "-", args.business_name.lower()).strip("-")
    archive_dir = os.path.join("assets", "letters")
    os.makedirs(archive_dir, exist_ok=True)
    archive_path = os.path.join(archive_dir, f"{safe_name}.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📄 Saved rendered copy to: {archive_path}")

    if args.show_html:
        print("\n" + "=" * 60)
        print("RENDERED HTML:")
        print("=" * 60)
        print(html)
        print("=" * 60 + "\n")

    # ── Build payload ─────────────────────────────────────────────────────────
    sender = default_sender()
    payload = build_payload(
        sender=sender,
        recipient_name=args.recipient_name,
        recipient_company=args.recipient_company,
        recipient_address=args.recipient_address,
        html_document=html,
        color=args.color,
        autoconfirm=args.autoconfirm,
    )

    # ── Dry run or send ───────────────────────────────────────────────────────
    if args.send:
        # Prefer OPENAPI_POST_TEST
        api_token = os.environ.get("OPENAPI_POST_TEST", "")
        test_mode = args.test_mode
        if api_token:
            test_mode = True
        else:
            api_token = os.environ.get("OPENAPI_POST", "")

        if not api_token:
            print("❌ No API token found in .env!", file=sys.stderr)
            print("   Set OPENAPI_POST_TEST or OPENAPI_POST in .env.", file=sys.stderr)
            return 1

        print(f"📮 Sending letter {'(SANDBOX)' if test_mode else ''} to: {args.recipient_name}")
        print(f"   Address: {args.recipient_address}")
        print(f"   Color: {'Yes' if args.color else 'No'}")
        print(f"   Autoconfirm: {'Yes' if args.autoconfirm else 'No'}")
        print()

        result = send_letter(payload, api_token=api_token, dry_run=False, test_mode=test_mode)

        if result.get("ok"):
            print("✅ Letter sent successfully!")
            data = result.get("data", {})
            
            # Log successful order details to assets/letters/orders.json
            try:
                order_log = os.path.join("assets", "letters", "orders.json")
                os.makedirs(os.path.dirname(order_log), exist_ok=True)
                
                try:
                    with open(order_log, "r", encoding="utf-8") as f:
                        history = json.load(f)
                except:
                    history = []
                    
                entry = {
                    "timestamp": datetime.now().isoformat(),
                    "business": args.business_name,
                    "recipient": args.recipient_name,
                    "api_response": data
                }
                history.append(entry)
                
                with open(order_log, "w", encoding="utf-8") as f:
                    json.dump(history, f, indent=2)
                print(f"💾 Order response logged to: {order_log}")
            except Exception as e:
                print(f"⚠️ Failed to log order: {e}")

            if isinstance(data, dict):
                # Single mail response
                order_data = data.get("data", [data])
                if isinstance(order_data, list) and order_data:
                    item = order_data[0]
                    print(f"   Order ID: {item.get('id', 'N/A')}")
                    print(f"   State: {item.get('state', 'N/A')}")
                    pricing = item.get("pricing", {})
                    totale = pricing.get("totale", {})
                    if totale:
                        print(f"   Cost: €{totale.get('importo_totale', '?')}")
        else:
            print(f"❌ API error (HTTP {result.get('status_code', '?')})")
            if "data" in result:
                print(json.dumps(result["data"], indent=2, ensure_ascii=False))
            elif "raw" in result:
                print(result["raw"][:500])
            return 1

        print("\n📋 Full API response:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Dry run — just print the payload
        print("\n🔍 DRY RUN — payload that would be sent:\n")

        # Print payload without the full HTML document (too verbose)
        display_payload = json.loads(json.dumps(payload))
        doc = display_payload.get("documento", [])
        if doc and isinstance(doc, list) and len(doc[0]) > 200:
            display_payload["documento"] = [f"[HTML document — {len(doc[0])} chars]"]

        print(json.dumps(display_payload, indent=2, ensure_ascii=False))
        print(f"\n📄 Letter HTML size: {len(html)} characters")
        print("\n💡 To actually send, run again with --send instead of --dry-run")

    return 0


if __name__ == "__main__":
    sys.exit(main())
