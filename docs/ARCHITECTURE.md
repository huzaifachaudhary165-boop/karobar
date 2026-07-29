# Architecture

## Shape of the system

```
Flutter client                    FastAPI backend                 Data
──────────────                    ───────────────                 ────
screens (features/)               endpoints (api/v1/)             SQLAlchemy models
   ↓ watch                           ↓ thin — no logic               ↑
Riverpod providers                services/                       SQLite (dev)
   ↓ call                            ↓ all business rules          Postgres/Supabase (prod)
repositories                      ai/ · integrations/
   ↓ HTTP                            ↓
ApiClient (dio)  ───────────────► Groq API · WhatsApp · Gmail
```

Two rules hold everywhere:

1. **Endpoints contain no business logic.** They authenticate, check a permission,
   call a service, and serialise. Every rule lives in `services/`, so the REST API,
   the AI tools and the sync engine all go through identical code paths.
2. **Nothing bypasses the tenant boundary.** `BaseService.base_query()` always filters
   by `business_id`; a service cannot be constructed without one.

---

## Backend layers

| Layer | Path | Responsibility |
|---|---|---|
| Core | `app/core/` | Config, DB engine, security, errors, logging, RBAC, money, portable column types |
| Models | `app/models/` | 36 tables. Multi-tenant, soft-delete, sync-aware |
| Schemas | `app/schemas/` | Pydantic request/response contracts |
| Services | `app/services/` | Every business rule |
| AI | `app/ai/` | Groq client, prompts, tool definitions, chat agent, OCR, insights |
| Integrations | `app/integrations/` | WhatsApp, Gmail/SMTP, SMS |
| API | `app/api/` | Routers and dependencies |

### The invoice engine

`VoucherService` is where the accounting actually happens. One table (`vouchers`)
holds every trade document, discriminated by `voucher_type`; behaviour differences
live on the enum rather than in separate tables:

```python
VoucherType.SALE.affects_stock    # True  → stock moves out
VoucherType.SALE.affects_ledger   # True  → party balance moves
VoucherType.QUOTATION.affects_stock  # False → nothing moves until converted
```

Creating a document runs a fixed sequence:

1. Resolve the party (fuzzy match by name, or create).
2. Build lines: snapshot the item, apply the line discount, split the tax
   (CGST+SGST intrastate, IGST interstate).
3. Compute totals; spread any document-level discount proportionally so tax stays correct.
4. Apply stock movements through `StockService` and only `StockService`.
5. Apply the party ledger delta.
6. Optionally record an inline payment.

Editing a posted document **reverses steps 4–5 before re-applying them**, so a stock
figure can never drift from its ledger.

### Money

Every amount is `Decimal`, stored as `NUMERIC(18,4)`. `app/core/money.py` is the only
place arithmetic happens. Floats appear nowhere in the money path.

### Stock

`Item.stock_qty` is a denormalised cache of an append-only `stock_ledger_entries`
table. `StockService` owns both, and `recalculate()` rebuilds the cache from the
ledger — the repair path when something does drift.

Weighted-average cost updates only on inward movements, which keeps COGS stable
when purchase prices move.

### Numbering

`NumberSequence` is a row-locked counter per (business, series, period). On Postgres
it takes `SELECT … FOR UPDATE`; SQLite serialises writes anyway. Two concurrent
invoices can never take the same number, and a user-typed number pushes the counter
past itself.

---

## The AI layer

The assistant is a tool-calling agent, not a text generator with a parser bolted on.

```
user message
   ↓
ChatAgent.chat()
   ↓ builds: system rules + business context + role-filtered tool list
Groq (openai/gpt-oss-120b)
   ↓ tool_use blocks
ToolExecutor  →  the same services the REST API uses
   ↓ tool_result blocks (fed back in ONE user message)
Groq
   ↓ final text + action chips
```

Design decisions worth knowing:

* **A manual tool loop, not the SDK runner.** Each turn has to persist raw content
  blocks, log every tool call for audit, enforce per-role permissions, and surface
  action chips. Those hooks are easier to own directly.
* **Tools are filtered by role before the model sees them.** A salesman's request
  never includes `adjust_stock`; the model cannot call what it was not offered.
* **Every AI write is logged** in `ai_tool_calls` with arguments, result, duration and
  the entity it touched. `Voucher.source = 'ai'` marks the record itself.
* **The wire format is translated in one file.** The app stores and replays content
  blocks; Groq speaks OpenAI chat completions. `client.py` converts both ways, so a
  stored transcript stays readable and the agent never sees provider details.
* **The model is a tested choice, not a default.** `llama-3.3-70b-versatile` cannot
  call tools on this app's prompts (`tool_use_failed`); `gpt-oss-120b` and
  `qwen3.6-27b` can. Changing `AI_MODEL` without testing a tool call will silently
  turn the assistant into a chatbot that promises to create invoices and doesn't.
* **The free tier's ceiling is tokens per minute**, so the client honours
  `retry-after` on a 429, retries once, and reports "the assistant is busy" rather
  than failing opaquely.
* **Refusals are handled** before reading content: a `content_filter` finish produces
  a polite reply in the user's language rather than a crash.

### Bill scanning

Split across two machines, which is what makes it free:

```
phone   ML Kit reads the photo → raw text      (offline, unlimited, no account)
   ↓    only the text is uploaded
server  gpt-oss-120b + a strict JSON schema → validated draft
   ↓
ocr_jobs row: extraction, confidence, warnings — nothing posted yet
   ↓    shopkeeper reviews and confirms
purchase bill or expense
```

Consequences worth knowing:

* No vision model is needed, which is why this runs on a free plan at all.
* The photo is optional. It is uploaded only for the shopkeeper's own records, and
  a failed upload does not cost them the scan.
* **`strictify()` rewrites the schema** before sending: strict structured output
  requires every property to appear in `required` at every level, with optionality
  expressed as a nullable type. Doing it in the client means a new schema cannot
  fail validation on its first real call.
* **A bottom-line tax figure is spread back onto the lines.** Bills print one tax
  total; the voucher engine derives tax per line. Without `_apply_document_tax` the
  saved bill would total less than the paper one — silently, which is the worst way
  for an accounting app to be wrong.

---

## Offline-first sync

```
device (offline)                     server
────────────────                     ──────
writes locally with a client_uuid
   │
   ├─ POST /sync/push  ─────────────► idempotent by client_uuid
   │                                  stale base_revision → conflict, not overwrite
   └─ GET  /sync/pull?since=<seq> ◄── change_logs feed, monotonic id
```

* **`client_uuid`** makes a retried upload update the same row instead of creating a twin.
* **`base_revision`** detects a stale edit. The server keeps its version and returns both,
  so the UI can ask the user instead of losing data.
* **`change_logs.id`** is the sync cursor — ordering *is* the contract, which is why it
  is a plain autoincrement integer rather than a UUID.
* A device never replays its own writes back to itself.
* Too far behind (>5000 changes) → `requires_full_sync`, and the client re-bootstraps.

### What that looks like on the phone

Two independent pieces, both backed by a local SQLite file (`drift`):

**The outbox** (`lib/data/local/app_database.dart`, `lib/data/sync_controller.dart`).
A form calls `saveOrQueue()`. If the request fails *because there is no signal*, the
change is written to the `outbox_entries` table and the form closes as a success —
the shopkeeper's work is safe. Anything else (422, 403, 409) still throws, because
the server saw the request and said no; retrying it later would fail identically.

`SyncController` watches `connectivity_plus` and drains the queue the moment a
connection returns. Rejections are triaged by reason:

| Server reason | What happens |
|---|---|
| `stale_revision` | Counted as an attempt and retried — a fresh read may resolve it |
| `validation`, `permission`, `not_found` | Parked (`is_blocked`) and surfaced to the user |
| 5 failed attempts | Parked, so one poisoned row can't stall everything behind it |

Queue order is insertion order, deliberately: a payment can reference an invoice
that is itself still waiting to upload.

**The read cache.** `ApiClient.get()` writes every good response to
`cached_responses`, keyed by path + sorted query *and business id*. When a read
fails with no signal, the last saved copy is served instead of an error screen.
Scoping by business id is what stops a shared phone showing one shop's data under
another shop's login; `wipe()` on sign-out clears both tables outright.

`SyncBanner` sits above every screen and shows nothing at all when there is nothing
wrong.

---

## Scale

The measurements that matter, taken against Supabase rather than guessed:

| Concern | Where it stands |
|---|---|
| Tenant indexes | All 32 `business_id` tables have a `business_id`-leading index |
| N+1 in lists | None: `/vouchers`, `/parties`, `/items` cost a constant 7–8 queries regardless of row count |
| Dashboard | 33 → 25 queries by batching period aggregates into one statement per table; pinned by a test that fails if it grows with data |
| Pagination | Capped at 200 per page in `page_params`, so no client can ask for everything |
| Rate limits | Sliding window per user/IP — **in-process**, so it holds on a container and does not on serverless |

The dashboard batching uses `SUM(CASE ...)` rather than Postgres' `FILTER` so the
same code runs on SQLite, and a test pins every batched figure to the
single-period helper it replaced.

### Connection pooling

The engine adapts to where it is running, because the right answer inverts:

* **Container** — a warm pool (20 + 10 overflow), `pool_pre_ping`, session
  pooler on port 5432.
* **Serverless** — `NullPool`, transaction pooler on port 6543. A frozen
  invocation holding a pooled connection open is a connection nobody can use;
  with enough concurrency that exhausts the database while almost nothing is
  running.

`settings.is_serverless` detects Vercel/Lambda automatically and
`app.cli check` reports the mismatches. See [DEPLOY.md](DEPLOY.md).

---

## Security

| Concern | Approach |
|---|---|
| Passwords | bcrypt, cost 12, SHA-256 pre-hash so >72-byte passwords keep their entropy |
| Sessions | JWT access (1h) + rotating refresh (60d), one DB row per session, individually revocable |
| Tenancy | Membership verified per request; a header cannot grant access you don't have |
| Permissions | Six roles → explicit permission sets, enforced in endpoints *and* in the AI tool layer |
| Integration tokens | Fernet-encrypted at rest, keyed off `SECRET_KEY` |
| File paths | Every stored name resolved and confined to the storage root |
| Rate limits | Sliding window per user/IP, tighter on auth and AI routes |
| Audit | Who changed what, when, from where — for every mutation |

---

## Flutter client

| Layer | Path | Responsibility |
|---|---|---|
| Core | `lib/core/` | Theme, network, storage, router, shared widgets, formatting, i18n |
| Data | `lib/data/` | DTOs, repositories, the local outbox/cache and the sync controller |
| State | `lib/providers.dart` | Riverpod providers and session state |
| Features | `lib/features/` | One folder per screen area |

* **Tokens** live in the OS keystore (`flutter_secure_storage`); everything else in
  shared preferences.
* **One refresh at a time**: concurrent 401s share a single refresh call and then replay.
* **Money formatting** uses Indian/Pakistani grouping (12,34,567) with tabular figures
  so columns line up.
* **Speech-to-text runs on-device** — voice input costs nothing and works on a weak
  connection; only the transcript reaches the server.
* **Roman Urdu stays LTR.** Only the Urdu wordmark forces RTL, because Roman Urdu —
  what shopkeepers actually type — is written left to right.
* **Barcode scanning is local too.** `mobile_scanner` reads the code on-device; only
  the resulting string hits `/items/barcode/{code}`. On the invoice screen the sheet
  reopens after each scan so a full basket can be rung up without tapping between
  items, and an unknown code offers to create the item with the barcode pre-filled.

### Sharing a shop

`business_members` is the join between a user and a business, carrying the role.
Every service filters by `business_id`, so sharing needs no separate code path —
adding a row is what grants access, and the tenant boundary does the rest.

Inviting someone with no account yet creates a **placeholder user** keyed to their
email or phone. They claim it by signing in with that same contact, through any
method: password, one-time code, or Google. There is no invite token, so there is
nothing to expire, leak, or forward to the wrong person.

Roles are resolved to permission sets in `app/core/permissions.py` and enforced in
two places — the endpoint (`tenant.require(...)`) and the AI tool list, which is
filtered by role *before* the model sees it. A salesman's assistant is not told
`adjust_stock` exists.

One rule the service protects directly: the last owner cannot be removed or
demoted, or the shop would become unadministrable.

### Sign-in

Three ways in, one session model. Password and one-time code are verified here;
Google is verified against Google's public keys (`google_login`), so the app only
ever carries an ID token and cannot assert who the user is.

A Google user who has never signed in before has no business, and every
tenant-scoped request would fail — so one is created for them at that moment,
named after them until they rename it. A user who was *invited* to someone else's
shop already has a membership, so nothing is created.

### First launch

The router gates on a single `onboarded` flag in shared preferences:

```
onboarded == false && signed out   →  /onboarding   (5 slides, language picker first)
onboarded == true  && signed out   →  /login
```

Once the user is inside, the dashboard shows a three-step checklist — first
customer, first item, first bill — computed live by `setupProgressProvider` from
the actual record counts. It removes itself permanently when all three are done, so
an established shop never sees it. Neither screen is ever shown twice by accident:
one is a stored flag, the other is derived from data.
