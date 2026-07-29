# Setup

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 tested |
| Flutter | 3.35+ | 3.41 tested (Dart 3.11) |
| SQLite | bundled | Postgres/Supabase for production |

---

## 1. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env        # cp on macOS/Linux
```

Open `.env` and set at least:

```ini
SECRET_KEY=<paste output of: python -c "import secrets;print(secrets.token_urlsafe(64))">
GROQ_API_KEY=gsk_...            # optional and free — everything except the AI works without it
```

Load demo data and start the server:

```bash
python -m app.cli seed          # demo shop: 276 invoices, 12 items, 8 parties
uvicorn app.main:app --reload
```

* API docs: <http://127.0.0.1:8000/docs>
* Health: <http://127.0.0.1:8000/health/ready>
* Demo login: `demo@karobar.app` / `demo1234`

CLI commands:

```bash
python -m app.cli check    # configuration report
python -m app.cli seed     # demo data
python -m app.cli reset    # drop and recreate every table
pytest                     # 86 tests
```

---

## 2. Mobile app

```bash
cd mobile
flutter pub get
dart run build_runner build      # generates the local database code (drift)
flutter run
```

`build_runner` writes `lib/data/local/app_database.g.dart`. It is generated, not
hand-written — run it again after changing any table in `app_database.dart`, or
`flutter analyze` will report the whole file as undefined.

### Android minimum version

`minSdk` is pinned to **23** in `android/app/build.gradle.kts` because the barcode
scanner's ML Kit reader needs it. That still covers Android 6 and up.

### Windows: enable Developer Mode first

Building **plugins** on Windows needs symlink support:

```
start ms-settings:developers
```

Turn on **Developer Mode**, then re-run `flutter pub get`. Without it, `flutter analyze`
and `flutter test` still work, but `flutter run` fails at the plugin step.

### Running on a phone over USB (easiest)

With the phone plugged in, one command builds, installs and launches it:

```powershell
.\scripts
un-on-phone.ps1            # debug, with hot reload
.\scripts
un-on-phone.ps1 -Release   # what you would hand to someone
```

It routes the phone to the API through the cable (`adb reverse`), so neither
Windows Firewall nor Android's cleartext rule gets in the way, and it refuses to
start a three-minute build if the API is not running.

The server must be up in another terminal:

```bash
cd backend
uvicorn app.main:app --port 8000
```

One trap it cannot detect for you: **two servers on port 8000**. A stale one bound
to `127.0.0.1` shadows a good one bound to `0.0.0.0`, and since `adb reverse`
targets loopback, the phone quietly talks to the stale build. Check with:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

### Testing on a real phone over Wi-Fi

Android 9+ refuses plain HTTP, so an APK pointed at your laptop fails with
"Cannot reach the server" until that address is allowed. HTTPS stays mandatory
and only local addresses are exempt, listed in
`android/app/src/main/res/xml/network_security_config.xml`:

```xml
<domain includeSubdomains="false">192.168.2.5</domain>   <!-- change to yours -->
```

Find yours with `ipconfig` (the Wi-Fi adapter's IPv4 address), put the phone on
the same Wi-Fi, and start the server so it listens beyond localhost:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

A deployed HTTPS server needs none of this.

### Pointing the app at your server

The app picks the right loopback per platform:

| Target | Default base URL |
|---|---|
| Android emulator | `http://10.0.2.2:8000/api/v1` |
| iOS simulator / desktop | `http://127.0.0.1:8000/api/v1` |

For a physical device or a deployed backend, override it at build time:

```bash
flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1
```

### Regenerating the app icons

Every launcher icon, adaptive icon, splash mark and iOS asset is generated from one
script, so the mark only has to be edited in one place:

```bash
pip install pillow
python scripts/generate_icons.py
```

It writes all five Android densities, the adaptive foreground/background pairs, the
monochrome (themed-icon) layer, the splash marks, the 15 iOS sizes, and
`assets/images/app_icon.png`. The same geometry lives in
`mobile/lib/core/widgets/karobar_logo.dart` as a `CustomPainter`, so the in-app mark
and the launcher icon can't drift apart — change one, re-run the script.

### Testing offline behaviour

You don't need to leave the house: stop the backend, or put the phone in aeroplane
mode. Lists keep rendering from the local cache, a saved bill goes into the outbox
with a banner showing the count, and starting the server again drains it. The queue
survives an app restart — it's on disk, not in memory.

---

## 3. Supabase / Postgres

### The database

One line changes:

```ini
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres
```

Two details that will otherwise cost you an afternoon:

* **Use the pooler host, not `db.<ref>.supabase.co`.** New Supabase projects give
  the direct host an IPv6-only address, which most home and office networks cannot
  reach. The symptom is a connection that hangs and then times out.
* **Use port 5432, not 6543.** 6543 is the transaction pooler, which cannot hold
  prepared statements — Alembic migrations fail against it. 5432 is session mode
  and works. The code disables statement caching on either, so both *run*; only
  migrations need 5432.

Percent-encode any `@ : / ?` in the password. A `.` or `-` is fine as-is.

Then create the schema:

```bash
alembic upgrade head        # or, for a throwaway environment:
python -m app.cli reset
```

Portable column types mean the same models run on SQLite and Postgres with no edits.
Verify with:

```bash
python -m app.cli check     # prints the host, reachability and the table count
```

### File storage

Uploads go to the server's disk by default, which is fine locally and wrong in
production — a redeployed container loses every scanned bill. To use Supabase
Storage:

1. Storage → New bucket → name it `karobar`, leave it **private**.
2. Settings → API → copy the **`service_role`** key (the secret one — the
   `sb_publishable_…` key cannot write from a server).

```ini
STORAGE_BACKEND=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
SUPABASE_BUCKET=karobar
```

The bucket stays private and downloads are proxied through `/api/v1/files/...`,
which checks the file belongs to the caller's business. The service key never
leaves the server, and no public object URL is ever handed out.

If `STORAGE_BACKEND=supabase` but the keys are missing, the app logs a warning and
falls back to disk rather than failing every upload.

Two things worth knowing, both learned by running it rather than reading docs:

* **Supabase returns HTTP 400 for a missing object**, with the real status inside
  the body (`{"statusCode":"404", ...}`). The client reads the body, so a deleted
  scan surfaces as "file not found" rather than "storage is broken".
* **Keep `MAX_UPLOAD_MB` under the bucket's own limit.** With the bucket at 50 MB
  and the app at 15, an oversized photo is refused with our message instead of
  Supabase's.

Tests never touch the bucket: `tests/conftest.py` forces `STORAGE_BACKEND=local`,
so running `pytest` against a configured `.env` cannot write into production
storage.

---

## 4. Optional integrations

### AI assistant and bill scanning

Get a free key at [console.groq.com](https://console.groq.com):

```ini
GROQ_API_KEY=gsk_...
AI_MODEL=openai/gpt-oss-120b
AI_FAST_MODEL=llama-3.1-8b-instant
AI_EFFORT=medium        # low | medium | high
```

**Model choice is not arbitrary.** The assistant works by calling tools, and not
every model on Groq can:

| Model | Tool calling | Notes |
|---|---|---|
| `openai/gpt-oss-120b` | yes | Default. Reads Roman Urdu correctly. |
| `qwen/qwen3.6-27b` | yes | Equivalent fallback. |
| `llama-3.3-70b-versatile` | **no** | Returns `tool_use_failed`. Do not use. |

**The free tier's real limit is tokens per minute, not requests per day.** A key
typically allows ~1,000 requests/day but only ~8,000 tokens/minute, and one
assistant turn with the full tool list costs 2–4k. So roughly two chat turns a
minute. The client reads Groq's own rate-limit headers, retries a 429 once after
the delay the server asks for, and logs `ai.budget_low` when the per-minute budget
drops below 2,000 tokens. Past that, users see "The assistant is busy right now" —
which is honest, not a crash.

That is fine for one shop. For many shops on one key it is not; you would move to a
paid Groq tier or another provider. Everything provider-specific lives in
`app/ai/client.py`.

Without a key the app runs fine — `/ai/*` returns a clear "not configured" error and
insights fall back to rule-based ones.

### Bill scanning needs no API at all

Reading the text off a photographed bill happens **on the phone**, using Google ML
Kit bundled into the app: free, unlimited, offline, no account. Only the extracted
text is sent to the server, which turns it into a draft purchase bill.

There is nothing to configure. It also means Groq's lack of a vision model doesn't
matter — the server never sees the image.

### Google Sign-In

Three OAuth ids, and the trap is that Android needs the **web** one:

1. Google Cloud Console → Credentials → **OAuth client ID → Web application**.
   That id is the audience of the ID token, so it goes in both places:

   ```ini
   GOOGLE_CLIENT_ID=<web client id>.apps.googleusercontent.com   # server verifies against this
   ```
   ```bash
   flutter run --dart-define=GOOGLE_SERVER_CLIENT_ID=<the same web client id>
   ```

2. Also create an **OAuth client ID → Android** with the package name
   `app.karobar.karobar` and your signing key's SHA-1. You never reference it in
   code; Google uses it to check the app is really yours.

Leave `GOOGLE_SERVER_CLIENT_ID` unset and the button hides itself rather than
failing on tap. Full walkthrough in [DEPLOY.md](DEPLOY.md).

### Printing

**Thermal receipts.** Pair the printer in Android's own Bluetooth settings
first — the app only lists already-paired devices, because pairing is a flow
people already know. Then Invoice → menu → **Print receipt**. The printer and
paper width are remembered after the first time.

Width matters more than it looks: 58mm is 32 characters across, 80mm is 48.
Choosing the wrong one wraps every line.

**Shelf labels.** Item → the label icon. Name, price and a scannable barcode,
however many copies you want. The barcode is drawn by the printer's own hardware
rather than sent as an image — crisp at any size and far quicker to transmit.
The symbology is chosen from the digits: EAN-13 and EAN-8 need an exact length
and a valid check digit, so anything else falls back to CODE39.

**A4 / A5.** Four layouts, set in Settings → Shop settings:

| Template | For |
|---|---|
| `classic` | Coloured header, one page. The default. |
| `minimal` | Black and white — prints on a tired inkjet, photographs well for WhatsApp |
| `gst` | Both GSTINs, place of supply, CGST/SGST or IGST split |
| `receipt` | 80mm roll through the OS print dialog |

### The daily summary

`POST /reports/daily-summary/send` delivers an end-of-day message on WhatsApp
and/or email — sale, cash collected, today's udhaar, total outstanding, and what
is running out.

Every figure is read from the ledger. No model is involved: a daily number that
is occasionally invented is worse than no daily number, and this one has to be
safe to act on.

Turn it off per shop with `daily_summary_enabled`. To send it nightly, call the
endpoint from cron or a scheduled task — there is no built-in scheduler, and one
process quietly holding a timer is a worse failure mode than a cron job you can
see.

### WhatsApp (Meta Cloud API)

```ini
WHATSAPP_ENABLED=true
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=karobar-verify-token
```

Point the Meta webhook at `https://your-host/api/v1/integrations/whatsapp/webhook`.

Not configured? Sharing still works — the app opens a pre-filled `wa.me` link instead.

### Email

Either Gmail OAuth:

```ini
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/integrations/gmail/callback
```

or an SMTP app password:

```ini
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password>
```

### SMS (for real OTP delivery)

```ini
OTP_DEV_MODE=false          # stop returning the code in the API response
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...
```

### Server-side PDF

`/vouchers/{id}/pdf` returns HTML with an `X-Pdf-Fallback: html` header when no PDF
engine is installed; the client renders it locally. For real server-side PDFs:

```bash
pip install -r requirements-pdf.txt
# Windows also needs the GTK3 runtime
```

---

## 5. Docker

```bash
docker compose up --build
```

Brings up Postgres and the API on <http://localhost:8000>. Set `GROQ_API_KEY`
in your shell first if you want the assistant enabled.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Building with plugins requires symlink support` | Enable Windows Developer Mode (above) |
| App shows "Cannot reach the server" | Wrong base URL — see the loopback table |
| `401` immediately after signing in | `SECRET_KEY` changed; old tokens are invalid. Sign in again |
| OTP never arrives | `OTP_DEV_MODE=true` returns it in the response instead of sending it |
| `/ai/chat` returns 503 | `GROQ_API_KEY` is missing, or AI is switched off in business settings |
| `/ai/chat` says "the assistant is busy" | Groq's free per-minute token budget is spent. Wait a minute, or lower `AI_MAX_TOKENS` |
| The assistant replies but never creates anything | Wrong model. `llama-3.3-70b-versatile` cannot call tools — use `openai/gpt-oss-120b` |
| Scanning says "no readable text" | A photo problem, not a server one: more light, bill flat, filling the frame |
| Postgres connection hangs then times out | You are using `db.<ref>.supabase.co`, which is IPv6-only. Use the pooler host |
| Alembic fails against Supabase | You are on port 6543 (transaction pooler). Migrations need 5432 |
| `insufficient_stock` on a sale | Working as intended. Enable `allow_negative_stock` in settings if your shop sells ahead of delivery |
| `Target of URI hasn't been generated: app_database.g.dart` | Run `dart run build_runner build` in `mobile/` |
| The intro slides won't show again | They're once-per-install by design. Clear app data, or reinstall, to see them |
| Camera opens black when scanning | Grant the camera permission; on Android 6–9 it's requested on first use |
| Changes stuck in the outbox | Open the banner → **Review**. A parked change is one the server refused for good; discard it or fix the record |
| "Continue with Google" is missing | `GOOGLE_SERVER_CLIENT_ID` was not passed at build time — by design, so it cannot fail on tap |
| Google sign-in fails with a config error | The SHA-1 in your Android OAuth client does not match the key the APK was signed with |
| Printer not listed | Pair it in Android's Bluetooth settings first — the app only shows paired devices |
| Receipt lines wrap oddly | Wrong paper width: 58mm is 32 characters, 80mm is 48 |
| Label prints name and price but no barcode | That item has no barcode saved |
| An invited person cannot get in | They must sign in with the *same* email or phone you invited — that is what claims the placeholder account |
