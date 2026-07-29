# کاروبار — Karobar

**AI-powered billing, inventory and accounting for small businesses.**
A Vyapar-class product with an AI layer on top: talk or type in plain Urdu, Hindi or
English and the assistant creates invoices, adds stock, records payments and answers
questions about the shop. Photograph a supplier bill and it becomes a purchase entry.

```
┌──────────────────────────────────────────────────────────────────┐
│  Flutter app (Android · iOS · Windows)                           │
│  offline-first · Riverpod · go_router · on-device speech         │
└───────────────────────────┬──────────────────────────────────────┘
                            │  REST + delta sync (JWT)
┌───────────────────────────┴──────────────────────────────────────┐
│  FastAPI backend                                                 │
│  auth · parties · items · invoices · payments · expenses         │
│  reports · sync · AI (chat + bill scanning + voice + insights)   │
└───────────────────────────┬──────────────────────────────────────┘
                            │  SQLAlchemy 2.0 async
┌───────────────────────────┴──────────────────────────────────────┐
│  SQLite (dev)  →  Postgres / Supabase (production)               │
└──────────────────────────────────────────────────────────────────┘
```

**It runs on free infrastructure.** The assistant uses Groq's free tier; bills are
read by Google ML Kit on the device, so no vision API is involved; the database and
file storage are Supabase's free plan. Barcode scanning and voice input are on-device
too. Nothing here bills per use.

---

## Quick start

```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env                              # set SECRET_KEY; GROQ_API_KEY for the AI
python -m app.cli seed                              # demo shop with 60 days of data
uvicorn app.main:app --reload                       # http://127.0.0.1:8000/docs

# Mobile
cd mobile
flutter pub get
dart run build_runner build                         # generates the offline database code
flutter run
```

Demo login: **demo@karobar.app** / **demo1234**

Full instructions, including Supabase and the Windows Developer-Mode requirement, are
in [docs/SETUP.md](docs/SETUP.md).

---

## What's built

| Area | Included |
|---|---|
| **Tenancy** | Multiple businesses per user, 6 roles, 25 granular permissions, full audit log |
| **Team** | Invite staff by email or phone — same shop, same data, role-scoped writes |
| **Sign-in** | Password, one-time code to a phone/email, or Continue with Google |
| **Parties** | Customers/suppliers, groups, ledger, ageing, credit limits, opening balances |
| **Inventory** | Items, services, categories, units, batches, expiry, godowns, append-only stock ledger, weighted-average cost |
| **Documents** | Sale · purchase · credit/debit note · quotation · proforma · delivery challan · orders |
| **Tax** | GST (CGST/SGST/IGST split by place of supply), Pakistan sales tax, HSN, GSTIN validation with checksum |
| **Money** | Payments in/out, FIFO settlement, partial payments, advances, cash/bank accounts, cheque tracking |
| **Expenses** | Categories, budgets, recurring, input-tax claim |
| **Reports** | Dashboard, P&L, balance sheet, sales, GSTR-style tax, daybook, cash flow, ageing |
| **AI** | Tool-calling assistant (15 tools), bill scanning, voice, business insights |
| **Sync** | Offline-first delta sync with idempotent replay and conflict detection |
| **Offline** | Local outbox for writes, read-through response cache, sync banner, one-tap retry |
| **Alerts** | Overdue payments, low stock, expiring batches, stale quotations — derived from live state |
| **Channels** | WhatsApp Cloud API, Gmail OAuth + SMTP, SMS, HTML/PDF invoices |
| **First run** | Five-screen intro with a language picker, then a setup checklist on the dashboard |
| **Hardware** | Barcode scanning for item lookup and straight onto a bill; camera OCR; on-device speech |
| **Printing** | Bluetooth thermal receipts (58/80mm ESC-POS), shelf labels with barcodes, four A4/A5 templates |
| **Your data** | One-file backup and restore, GSTR-1 export (JSON + CSV), clear-transactions |
| **Languages** | Full UI in English, Roman Urdu and Roman Hindi — 133 sentences, keyed by source text |
| **Daily summary** | End-of-day WhatsApp/email message: sale, cash, udhaar, what ran out |
| **Branding** | Urdu wordmark, generated launcher icons for every density, adaptive icon, native splash |

---

## Three things worth a closer look

### The assistant performs real work

"Ahmed ko 5 bori cement becha 1290 ka" resolves the customer, matches the item,
creates the invoice, moves stock and updates the ledger — through the **same
services the REST API uses**. There is no shortcut path into the database, so an
AI-created invoice is audited, permission-checked and reversible exactly like a
hand-typed one. Verified end to end, not in theory:

```
reply    Cement 5 bori @ 1,290 = Rs 6,450. Ahmed Traders ko invoice
         INV-2026-27/0001 ban gaya, due Rs 6,450.
tools    search_parties → search_items → create_invoice
db       INV-2026-27/0001 · Ahmed Traders · 6450.0000 · unpaid
stock    Cement Bori 100 → 95
```

Note what the prompt has to teach: in Urdu "1290 ka" means *1290 each*, not a total
of 1290. Getting that wrong produces a plausible invoice with the wrong money on it.

Tools are filtered by role *before* the model sees them: a salesman's request never
contains `adjust_stock`, so the model cannot call it.

### Bill scanning costs nothing to run

The photo is read **on the phone** by Google ML Kit — free, unlimited, works with no
signal, no account. Only the extracted text goes to the server, which turns it into
a draft purchase bill against a strict JSON schema.

That split is why this needs no vision model, and it puts the error-prone half
(character recognition) where the photo already is. A bottom-line tax figure is
spread back onto the line items, because the voucher engine derives tax per line —
without that the saved bill would quietly total less than the paper one.

### The invoice engine is reversible

Editing or cancelling a posted document **reverses its stock movements and ledger
delta before re-applying them**. `Item.stock_qty` is a cache over an append-only
stock ledger, and `recalculate()` rebuilds it from source — so the live figure and
the ledger can never quietly disagree.

Every amount is `Decimal` end to end. No float touches the money path.

### Sync detects conflicts instead of losing data

Each offline write carries a `client_uuid` (a retried upload updates the same row
instead of creating a twin) and a `base_revision`. A stale edit comes back as a
conflict with both versions attached, so the UI can ask the user — rather than
silently overwriting whatever the other device wrote.

On the phone this is a **drift-backed outbox**: a bill saved with no signal is
queued locally, the banner says how many changes are waiting, and the queue drains
the moment connectivity returns. Reads are separately cached, so the item list and
dashboard still render offline. Rejections are triaged — a stale revision is
retried, a validation error is parked for the user to look at, so one bad row can
never block the queue.

### Screens open before the network answers

Every successful GET is written to a local SQLite table. The busy screens —
dashboard, parties, items, invoices — read that copy **first** and paint from it,
then replace it when the server responds. Against a database a few hundred
milliseconds away that is the difference between a spinner and no spinner, and it
is the same table that serves those screens when the phone has no signal at all.

If the network then fails after cached data was shown, the error is deliberately
swallowed: the user is looking at usable figures and the banner already says the
connection is down.

### One shop, several people

The owner invites someone by email or phone number and picks what they can do.
There is no invite link to forward or lose — the server creates a placeholder
account against that contact, and the person claims it by signing in with the same
email or number. Tested end to end: an invited salesman lands in the owner's shop,
sees their customers, can write a bill, and gets a `403` on stock adjustment.

### Alerts are recomputed, never accumulated

`POST /notifications/refresh` rebuilds the whole list from current state: overdue
invoices, items under their low-stock level, batches nearing expiry, quotations
nobody replied to. An alert for a bill that has since been paid doesn't get marked
read — it stops existing. That means the bell's count is always true, with no
background job to keep in step.

---

## Testing

```bash
cd backend && pytest              # 86 tests over the real ASGI app + DB
cd mobile && flutter analyze      # zero issues
cd mobile && flutter test         # 28 tests: formatting, the Urdu logo, the outbox, translations
```

The backend tests exercise real behaviour, not mocks: invoice arithmetic and tax
splits, stock going negative, FIFO settlement, cancel-restores-everything, business
isolation across tenants, role enforcement, the sync conflict path, and that alerts
appear and disappear as the underlying condition changes.

They also cover the two seams the Groq switch introduced: the block ⇄ OpenAI wire
translation (a dropped `tool_call_id` corrupts a turn invisibly), and the OCR tax
spread (without it a scanned bill silently totals less than the paper one).

The mobile outbox tests run against a real in-memory SQLite database — queue
ordering, idempotent re-queuing, blocked-vs-retryable failures, per-business cache
isolation and the sign-out wipe.

---

## Layout

```
backend/
  app/
    core/          config · db · security · errors · RBAC · money · portable types
    models/        36 tables — multi-tenant, soft-delete, sync-aware
    schemas/       Pydantic contracts
    services/      every business rule
    ai/            Groq client · prompts · tools · agent · OCR · insights
    integrations/  WhatsApp · Gmail/SMTP · SMS
    api/v1/        routers and dependencies
  alembic/         migrations
  tests/
mobile/
  lib/
    core/          theme · network · storage · router · widgets · i18n
    data/          models · repositories · local outbox/cache (drift) · sync controller
    features/      onboarding · auth · dashboard · parties · items · invoices · payments ·
                   expenses · notifications · assistant · reports · settings
  android/ ios/    manifests, adaptive icons, splash themes, usage descriptions
docs/              SETUP · ARCHITECTURE · API · AI
scripts/           dev.ps1 · dev.sh · generate_icons.py
assets/            generated launcher marks and the app icon
```

~31,500 lines across 133 hand-written source files.

---

## Documentation

* [docs/SETUP.md](docs/SETUP.md) — install, configure, Supabase, integrations, troubleshooting
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the invoice engine, sync and AI layer work
* [docs/API.md](docs/API.md) — every endpoint, with request/response shapes
* [docs/AI.md](docs/AI.md) — prompt design, tool contracts, OCR schema, rate limits
* [docs/DEPLOY.md](docs/DEPLOY.md) — Vercel and container hosting, the APK build, Google Sign-In setup

---

## Licence / attribution

Karobar is an independent product. It is **not** affiliated with, endorsed by, or
derived from the source code of Vyapar or any other vendor — the feature set is
re-implemented from scratch.
