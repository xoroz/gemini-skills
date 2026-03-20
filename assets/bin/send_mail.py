#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
TexNGo — SMTP mailer
====================
Sends a plain-text or HTML e-mail via OVH (or any STARTTLS SMTP server).
Credentials are read from the project .env file; CLI args override From/To.

Usage
-----
    python assets/bin/send_mail.py <from> <to> <subject> <body> [attachment]

    <from>       Sender address  (overrides SMTP_USER from .env if different)
    <to>         Recipient address (comma-separated for multiple)
    <subject>    Email subject line
    <body>       Message body — plain text OR a path to an .html file
    [attachment] Optional path to a file to attach

Examples
--------
    python assets/bin/send_mail.py \
        [email protected] [email protected] \
        "Ciao dal sito" "Il tuo sito è pronto!"

    python assets/bin/send_mail.py \
        [email protected] [email protected] \
        "Flyer allegato" "Vedi allegato." /path/to/flyer.png

    python assets/bin/send_mail.py \
        [email protected] [email protected] \
        "Benvenuto" /path/to/welcome.html

.env keys read
--------------
    SMTP_HOST   default: ssl0.ovh.net
    SMTP_PORT   default: 587
    SMTP_USER   required (sender login)
    SMTP_PASS   required (sender password)
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader  (no third-party deps required)
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file and return key→value pairs (no shell expansion)."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        env[key] = val
    return env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_body(body_arg: str) -> tuple[str, bool]:
    """
    If body_arg is a path to an existing .html file, read and return it
    as (content, is_html=True).  Otherwise treat it as literal text.
    """
    # Safety check: if the string is very long or contains newlines, 
    # it's definitely not a file path. This avoids 'File name too long' errors.
    if len(body_arg) < 1024 and "\n" not in body_arg:
        try:
            p = Path(body_arg)
            if p.is_file() and p.suffix.lower() in (".html", ".htm"):
                return p.read_text(encoding="utf-8"), True
        except OSError:
            pass

    # Detect inline HTML heuristic
    stripped = body_arg.lstrip()
    if stripped.startswith("<") and ("</") in body_arg:
        return body_arg, True
    return body_arg, False


def _attach_file(msg: EmailMessage, path: str) -> None:
    """Guess MIME type and attach a file to the message."""
    p = Path(path)
    if not p.is_file():
        print(f"⚠️  Attachment not found, skipping: {path}", file=sys.stderr)
        return

    mime_type, _ = mimetypes.guess_type(str(p))
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    data = p.read_bytes()
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)
    print(f"📎  Attached: {p.name}  ({len(data):,} bytes, {maintype}/{subtype})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # ── Parse CLI ──────────────────────────────────────────────────────────
    ap = argparse.ArgumentParser(
        description="Send an email via SMTP (reads creds from .env).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("from_addr",  help="Sender email address")
    ap.add_argument("to_addr",    help="Recipient(s) — comma-separated for multiple")
    ap.add_argument("subject",    help="Email subject line")
    ap.add_argument("body",       help="Body text, inline HTML, or path to .html file")
    ap.add_argument("attachment", nargs="?", default=None, help="Optional file to attach")

    args = ap.parse_args()

    # ── Load .env (project root = two levels up from assets/bin/) ──────────
    script_dir  = Path(__file__).resolve().parent          # assets/bin/
    project_dir = script_dir.parent.parent                 # project root
    env_file    = project_dir / ".env"
    env         = _load_dotenv(env_file)

    # Merge with os.environ (os.environ takes priority)
    def _get(key: str, default: str = "") -> str:
        return os.environ.get(key) or env.get(key) or default

    SMTP_HOST = _get("SMTP_HOST", "ssl0.ovh.net")
    SMTP_PORT = int(_get("SMTP_PORT", "587"))
    SMTP_USER = _get("SMTP_USER")
    SMTP_PASS = _get("SMTP_PASS")

    if not SMTP_USER or not SMTP_PASS:
        print("❌  SMTP_USER and SMTP_PASS must be set in .env or environment.", file=sys.stderr)
        sys.exit(1)

    # ── Resolve body ───────────────────────────────────────────────────────
    body_text, is_html = _resolve_body(args.body)
    recipients = [r.strip() for r in args.to_addr.split(",") if r.strip()]

    # ── Build message ──────────────────────────────────────────────────────
    BCC_COPY = "info@texngo.it"

    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"]    = args.from_addr
    msg["To"]      = ", ".join(recipients)
    msg["Bcc"]     = BCC_COPY

    if is_html:
        # Set plain-text fallback then add HTML alternative
        plain = "Apri questa email in un client che supporta HTML."
        msg.set_content(plain)
        msg.add_alternative(body_text, subtype="html")
    else:
        msg.set_content(body_text)

    # ── Attach file (optional) ─────────────────────────────────────────────
    if args.attachment:
        _attach_file(msg, args.attachment)

    # ── Send ───────────────────────────────────────────────────────────────
    print(f"📧  Sending via {SMTP_HOST}:{SMTP_PORT}")
    print(f"    From    : {args.from_addr}")
    print(f"    To      : {', '.join(recipients)}")
    print(f"    Bcc     : {BCC_COPY}")
    print(f"    Subject : {args.subject}")
    print(f"    Body    : {'HTML' if is_html else 'plain text'}  ({len(body_text):,} chars)")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print("✅  Email sent successfully!")
    except smtplib.SMTPAuthenticationError:
        print("❌  Authentication failed — check SMTP_USER / SMTP_PASS in .env", file=sys.stderr)
        sys.exit(1)
    except smtplib.SMTPException as exc:
        print(f"❌  SMTP error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"❌  Network error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
