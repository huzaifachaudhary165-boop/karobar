# API reference

Base URL: `/api/v1` · Interactive docs at `/docs`

## Conventions

**Auth** — every route except `/health*`, `/auth/*` and the WhatsApp webhook needs:

```http
Authorization: Bearer <access_token>
X-Business-Id: <business uuid>     # optional; falls back to the token's business
X-Device-Id: <stable per-install>  # required by /sync
```

**Errors** always use the same envelope:

```json
{
  "error": { "code": "insufficient_stock", "message": "Not enough stock for 'Sugar'…", "details": {} },
  "request_id": "b414d49868fe4e4e"
}
```

| Code | HTTP | Meaning |
|---|---|---|
| `unauthenticated` | 401 | Sign in again |
| `forbidden` | 403 | Role lacks the permission |
| `not_found` | 404 | No such record in this business |
| `conflict` | 409 | Duplicate name / number |
| `validation_error` | 422 | `details.fields` maps field → message |
| `business_rule_violation` | 422 | e.g. `insufficient_stock` |
| `rate_limited` | 429 | `details.retry_after_seconds` |
| `ai_not_configured` | 503 | No `GROQ_API_KEY` |
| `ai_rate_limited` | 503 | Groq's per-minute token budget is spent |

**Lists** are paginated: `?page=1&size=25&sort=name&order=asc` →

```json
{ "items": [...], "total": 148, "page": 1, "size": 25, "pages": 6, "has_next": true, "has_prev": false }
```

---

## Auth

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create account (+ first business in the same call) |
| POST | `/auth/login` | Password sign-in |
| POST | `/auth/otp/send` | Send a one-time code (returns it when `OTP_DEV_MODE`) |
| POST | `/auth/otp/verify` | Verify — signs in, or creates the account |
| POST | `/auth/google` | Google ID-token sign-in |
| POST | `/auth/refresh` | Rotate tokens |
| POST | `/auth/logout` · `/auth/logout-all` | End one or all sessions |
| GET | `/auth/me` · `/auth/sessions` | Current user, active sessions |
| POST | `/auth/switch-business` | Change the active business |
| POST | `/auth/change-password` · `/auth/reset-password` | Password management |

---

## Business

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/businesses` | List / create |
| GET/PATCH | `/businesses/current` | Active business profile |
| GET/PATCH | `/businesses/current/settings` | Numbering, tax, print, reminders, AI toggles |
| GET | `/businesses/current/permissions` | What this role can do |
| GET/POST | `/businesses/current/members` | Team |
| PATCH/DELETE | `/businesses/current/members/{id}` | Change role / remove |

## Parties

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/parties` | List (filters: `search`, `party_type`, `only_receivable`, `only_payable`) / create |
| GET | `/parties/search?q=` | Fuzzy name+phone match, with confidence |
| GET | `/parties/ageing?direction=` | Receivable / payable buckets |
| GET/PATCH/DELETE | `/parties/{id}` | One party |
| GET | `/parties/{id}/ledger` | Running statement |
| POST | `/parties/{id}/recalculate` | Rebuild the balance from source rows |
| GET/POST | `/parties/groups` | Party groups |

## Items & stock

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/items` | List (`search`, `only_low_stock`, `only_out_of_stock`) / create |
| GET | `/items/search?q=` | Fuzzy item match |
| GET | `/items/barcode/{barcode}` | Scan lookup |
| GET | `/items/stock/summary` | Value, low-stock and out-of-stock counts |
| POST | `/items/stock/adjust` | Signed adjustment with a reason |
| GET/PATCH/DELETE | `/items/{id}` | One item |
| GET | `/items/{id}/ledger` | Stock movements |
| GET/POST | `/items/categories` · `/items/units` | Masters |

## Invoices

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/vouchers` | List / create any document type |
| GET | `/vouchers/next-number?voucher_type=` | Preview without consuming |
| GET/PATCH/DELETE | `/vouchers/{id}` | One document |
| POST | `/vouchers/{id}/cancel` | Reverse stock + ledger, keep the record |
| POST | `/vouchers/{id}/convert` | Quotation/order → invoice |
| POST | `/vouchers/{id}/return` | Credit or debit note |
| GET | `/vouchers/{id}/html` · `/pdf` | Print-ready output |
| POST | `/vouchers/{id}/share` | WhatsApp / email / SMS / link |

`voucher_type`: `sale · purchase · sale_return · purchase_return · quotation · proforma · delivery_challan · sale_order · purchase_order`

<details><summary>Create-invoice body</summary>

```json
{
  "voucher_type": "sale",
  "party_id": "…",
  "voucher_date": "2026-07-28",
  "lines": [
    { "item_id": "…", "qty": 10, "rate": 7400, "discount_type": "percent", "discount_value": 5 }
  ],
  "payment": { "amount": 50000, "mode": "cash" }
}
```
</details>

## Payments & expenses

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/payments` | List / record |
| POST | `/payments/settle` | Settle a party, oldest invoice first |
| GET/PATCH/DELETE | `/payments/{id}` | One payment |
| GET/POST | `/payments/accounts` | Cash and bank accounts |
| GET/POST | `/expenses` | List / record |
| GET | `/expenses/breakdown` | Spend by category |
| GET/POST | `/expenses/categories` · `/expenses/tax-rates` | Masters |

## Notifications

Alerts are **derived, not stored events**. `refresh` recomputes the entire list
from current business state and deletes anything that is no longer true, so the
unread count can never drift from reality. Read flags survive a refresh — an alert
you already looked at stays read as long as the underlying condition holds.

| Method | Path | Purpose |
|---|---|---|
| GET | `/notifications` | List. `?only_unread=true`, `?kind=`, `?page=`, `?size=` |
| GET | `/notifications/count` | `{"unread": 4}` — what the bell badge shows |
| POST | `/notifications/refresh` | Recompute from live state; returns the new list |
| POST | `/notifications/{id}/read` | Mark one read |
| POST | `/notifications/read-all` | Mark everything read |
| DELETE | `/notifications` | Clear the list |

Kinds: `payment_due` (an invoice past its due date), `low_stock` (at or below the
item's low-stock level), `expiring_stock` (a batch nearing expiry),
`stale_quotation` (sent, no reply, still open).

<details><summary>A notification</summary>

```json
{
  "id": "...",
  "kind": "payment_due",
  "title": "Ahmed Traders — 12,400 overdue",
  "body": "INV-0042 was due 6 days ago.",
  "channel": "in_app",
  "entity_type": "voucher",
  "entity_id": "...",
  "data": { "route": "/invoices/<id>", "days_overdue": 6 },
  "is_read": false,
  "created_at": "2026-07-28T09:12:00Z"
}
```

`data.route` is what the app deep-links to when the row is tapped.
</details>

## Your data

| Method | Path | Purpose |
|---|---|---|
| GET | `/data/backup` | The whole shop as one JSON file |
| POST | `/data/restore` | Load a backup back in. Adds what is missing; `?replace=true` to wipe first |
| GET | `/data/gstr1` | GSTR-1 for a period. `?format=csv` for a spreadsheet |
| DELETE | `/data/clear` | Delete every transaction, keeping customers and items |

A restore keeps the original row ids, so importing the same file twice adds
nothing the second time. `business_id` is always overwritten with the caller's —
a file cannot claim to belong to another shop.

GSTR-1 splits into `b2b` / `b2cl` / `b2cs` / `hsn` the way the portal's offline
utility expects, and lists anything it could not place under `needs_attention`
(usually a customer with no state code). It produces the file; **filing** through
the GSTN API needs a licensed GSP, which no free tool can offer.

## Reports

`GET /reports/…` — `dashboard`, `profit-loss`, `balance-sheet`, `sales`, `tax`,
`daybook`, `cash-flow`, `ageing`, `top-items`, `top-parties`,
`daily-summary`, and `POST /reports/daily-summary/send`.

All accept `?period=today|this_week|this_month|last_month|this_quarter|this_year|fy|last_7_days|last_30_days`
or an explicit `start_date` / `end_date`.

---

## AI

| Method | Path | Purpose |
|---|---|---|
| POST | `/ai/chat` | Tool-calling assistant — creates real records |
| POST | `/ai/voice` | Same, from a speech transcript |
| POST | `/ai/transcribe` | Audio → text via Whisper, hinted with this shop's own item and customer names |
| POST | `/ai/chat/stream` | SSE text stream (read-only, no tools) |
| GET | `/ai/suggestions` | Contextual prompt chips |
| GET/DELETE | `/ai/conversations[/{id}]` | Chat history |
| POST | `/ai/ocr/scan` | Device-read text → structured draft |
| POST | `/ai/ocr/apply` | Draft → purchase bill or expense |
| GET | `/ai/ocr/jobs[/{id}]` | Scan history |
| POST/GET | `/ai/insights` | Generated business insights |
| GET | `/ai/usage` | This month's tokens and estimated cost |

<details><summary>Chat request and response</summary>

```json
// POST /ai/chat
{ "message": "Ahmed ko 5 bori cement becha 1290 ka", "conversation_id": null }
```

```json
{
  "conversation_id": "…",
  "reply": "Ho gaya. INV-2026-27/0123 · Ahmed Traders · Rs 7,546",
  "actions": [
    {
      "tool": "create_invoice",
      "label": "Invoice created",
      "status": "done",
      "summary": "INV-2026-27/0123 · Ahmed Traders · Rs 7,546",
      "entity_type": "voucher",
      "entity_id": "…",
      "deep_link": "/invoices/…"
    }
  ],
  "suggestions": ["WhatsApp par bhejo", "Payment entry karo"],
  "input_tokens": 4210, "output_tokens": 180, "latency_ms": 3420
}
```
</details>

**Tools the assistant can call** — reads: `search_parties`, `get_party_details`,
`search_items`, `get_stock_report`, `get_business_summary`, `list_invoices`,
`get_outstanding`, `get_top_items`. Writes: `create_party`, `create_item`,
`create_invoice`, `record_payment`, `record_expense`, `adjust_stock`,
`update_item_price`.

Each tool is permission-gated: a role that cannot perform an action never sees the
tool, so the model cannot call it.

---

## Sync

| Method | Path | Purpose |
|---|---|---|
| GET | `/sync/bootstrap` | Everything a fresh install needs, in one call |
| POST | `/sync/push` | Upload offline changes |
| GET | `/sync/pull?since=<seq>` | Download the delta feed |
| GET | `/sync/status` | How far behind this device is |

<details><summary>Push body and conflict shape</summary>

```json
{
  "device_id": "dev_abc123",
  "changes": [
    {
      "entity": "party",
      "operation": "create",
      "client_uuid": "offline-party-0001",
      "data": { "name": "New Customer", "party_type": "customer" }
    }
  ]
}
```

A stale edit comes back as a conflict rather than an overwrite:

```json
{
  "conflicts": [
    {
      "entity": "party",
      "client_uuid": "…",
      "reason": "stale_revision",
      "message": "This record was changed on another device after your edit.",
      "server_revision": 4,
      "server_data": { "…": "…" }
    }
  ]
}
```
</details>

## Files & integrations

| Method | Path | Purpose |
|---|---|---|
| POST/GET/DELETE | `/files[/{id}]` | Upload, download, delete |
| GET | `/integrations` | Connection status per channel |
| GET/DELETE | `/integrations/gmail/connect` · `/gmail` | Gmail OAuth |
| GET/POST | `/integrations/whatsapp/webhook` | Meta verification and delivery callbacks |
| POST | `/integrations/reminders/{party_id}` | Send a payment reminder |
