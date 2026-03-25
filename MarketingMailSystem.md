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
    - **Address Parser**: Converts free-form Italian addresses (e.g., `"Via Roma 1, 00100 Roma RM"`) into the structured fields required by the Posta Ordinaria API (`dug`, `indirizzo`, `civico`, `cap`, `comune`, `provincia`).
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
    - A copy of the rendered letter is **automatically saved** to `assets/letters/<business_name>.html`.
    - Successful order details (ID, pricing, state) are logged into `assets/letters/orders.json` for tracking.
5.  **Postal API Call**:
    - The HTML is sent as the `documento`.
    - The API handles the conversion to **PDF**, printing, folding, stuffing into an envelope, and mailing.
6.  **Response**: Returns an **Order ID**, **State (e.g., CONFIRMED)**, and the calculated **Cost**.

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
- **Address Validation**: The Ufficio Postale API strictly validates the CAP/Comune/Provincia combination. If you get a **422 Error**, double-check the address (e.g., use `00187` for Roma RM instead of a generic `00100`).
- **Sandbox vs. Prod**: The sandbox environment (`test.ws.ufficiopostale.com`) is used automatically when `OPENAPI_POST_TEST` is the primary key. This is the safest way to iterate on design without spending real money.
