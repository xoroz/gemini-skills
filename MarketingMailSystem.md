# TexNGo Marketing Mail System (Email & Physical Letters)

This system enables automated marketing campaigns to deliver AI-generated website previews to potential customers. It supports both **HTML emails** (SMTP) and **physical printed letters** (OpenAPI Ufficio Postale).

---

## 🏗️ System Components

### 1. Template Engine
Located in `assets/emails/` and `assets/letters/`.
- **Email Templates**: `template_sorpresa.html`, `template_offerta.html`, `template_diretto.html`.
- **Physical Letter Template**: `template_lettera.html` — A4 print-optimized, mirrors the formal tone of the "Diretto" email.
- **Variable Substitution**: Both systems use `${variable}` placeholders (e.g., `${business_name}`, `${site_url}`) rendered via Python's `string.Template`.

### 2. Builders (Logic Modules)
- **`scripts/email_builder.py`**: Handles email rendering and subject generation.
- **`scripts/letter_builder.py`**:
    - **Address Parser**: Converts free-form Italian addresses into structured API fields. Uses a dynamic extraction engine powered by an `_ITALIAN_PROVINCES` database to safely extract `CAP` and `Provincia` anywhere in the string, heavily reducing manual correction needs. Also handles extreme street lengths by auto-truncating to meet strict OpenAPI limits (44 chars).
    - **API Integration**: Connects to `https://ws.ufficiopostale.com` (Production) or `https://test.ws.ufficiopostale.com` (Sandbox).

### 3. CLI Testing Tools
Used for manual verification and one-off mailings:
- **`scripts/letter_sender.py`**:
    - `--dry-run` (Default): Prints the JSON payload without sending (zero cost).
    - `--send`: Actually triggers a mailing.
    - `--test-mode`: Force usage of the Sandbox environment.
    - `--show-address`: Debug mode to see how an address string is parsed.

---

## 📮 Physical Letter Workflow (OpenAPI Ufficio Postale)

1.  **Request**: `POST /send-letter` is called via FastAPI.
2.  **Resolution**: The system looks up the `business_name` from the internal registry based on the site `slug`.
3.  **URL Building**: A public preview URL is generated (e.g., `https://dev.texngo.it/slug/index.html`).
4.  **Rendering & Archiving**:
    - The `template_lettera.html` is rendered with business details.
    - A copy of the rendered letter is **automatically saved** to `assets/letters/<slug>.html`.
5.  **Postal API Call & Logging**:
    - The HTML is sent as the `documento`. Full raw JSON request/response payloads are tracked in **`logs/letter.log`** (isolated from `backend.log`).
    - The API handles the conversion to **PDF**, printing, folding, and mailing.
6.  **Response & Tracking**: 
    - The API returns an **Order ID**, **State**, PDF URL, and **Cost**.
    - These key details are appended in a clean, minimal format to **`assets/letters/orders.json`**.
7.  **Live Updates**: Calling the `GET /check-letter/{order_id}` endpoint fetches the latest delivery state from OpenAPI and **automatically rewrites** `orders.json` so the local database stays in sync with real-world delivery tracking.

### 💶 Cost Breakdown (Approximate)
| Service | Cost (Posta Ordinaria) |
|---|---|
| Postage (Single pg) | ~€1.10 |
| Printing | ~€0.22 |
| Enveloping | ~€0.26 |
| **TOTAL (excl. IVA)** | **€1.58** |
| *Color printing* | *+~€0.20–0.80* |

---

## 🛠️ Configuration (.env)

### Physical Letters (API)
- `OPENAPI_POST`: Production API token.
- `OPENAPI_POST_TEST`: Sandbox/Test API token. If this key is present, the system **automatically switches to the Sandbox URL**.
- `LETTER_SENDER_*`: Configures the return address printed on the envelope (e.g., `LETTER_SENDER_NAME=TexNGo`).

### Emails (SMTP)
- `SMTP_HOST`, `SMTP_PORT`: Mail server settings (Default: OVH SSL).
- `SMTP_USER`, `SMTP_PASS`: Credentials.

---

## 🚀 Execution Commands

### Send a Test Letter (Sandbox)
```bash
uv run scripts/letter_sender.py \
  --business-name "Test Business" \
  --niche "test" \
  --site-url "https://dev.texngo.it/test/index.html" \
  --recipient-name "Mario Rossi" \
  --recipient-address "Piazza Barberini 2, 00187 Roma RM" \
  --send --test-mode --autoconfirm
```

### Trigger via API (curl)
```bash
curl -X POST "https://dev.texngo.it/send-letter" \
  -H "Authorization: Bearer <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "estetica-lara",
    "recipient_name": "Mario Rossi",
    "recipient_address": "Piazza Barberini 2, 00187 Roma RM",
    "dry_run": false
  }'
```

---

## ⚠️ Important Notes
- **Address Validation (12027 Conflict)**: The Ufficio Postale API strictly validates that the CAP, Comune, and Provincia match their official database. If Google Maps provides a *Frazione* (e.g., "Marina di Carrara"), the API may throw a `12027` error. Users can simply edit the Comune field to the official municipality in the frontend modal to bypass this.
- **Troubleshooting**: Check `logs/letter.log` to see the exact JSON payload sent to the API and the exact error returned if a letter fails to send.
- **Sandbox vs. Prod**: The sandbox environment (`test.ws.ufficiopostale.com`) is used automatically when `OPENAPI_POST_TEST` is active. This ensures 100% free structural testing.
