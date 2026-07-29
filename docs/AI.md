# The AI layer

Three surfaces, running on Groq's free tier (`openai/gpt-oss-120b` by default):

| Surface | What it does | Where |
|---|---|---|
| Assistant | Tool-calling agent that creates real records | `app/ai/agent.py`, `tools.py` |
| Scanning | Bill photo → structured draft → purchase or expense | phone + `app/ai/ocr.py` |
| Insights | Narrates the shop's actual figures | `app/ai/insights.py` |

Everything routes through `app/ai/client.py`, so token spend, latency, throttling
and wire-format translation live in one place.

### Two formats, one seam

The app speaks **content blocks** — `text`, `tool_use`, `tool_result` — because that
is what `ai_messages.blocks` stores, and a stored transcript has to round-trip
exactly or the next turn is built on a corrupted history. Groq speaks the OpenAI
chat-completions shape.

`client.py` translates both ways and nothing else in the codebase knows the
difference. The one structural mismatch worth naming: we keep every result of a
parallel tool batch inside a single user turn, while OpenAI wants one `tool` message
per call — so one of our messages expands into several of theirs. Lose one and the
next request 400s with a `tool_call` that has no result.

---

## The assistant

### Why a manual tool loop

The SDK's tool runner is the usual recommendation, but each turn here has to:

* persist raw content blocks to Postgres so `tool_use`/`tool_result` round-trip exactly,
* log every tool call to `ai_tool_calls` for audit,
* enforce per-role permissions before a tool runs,
* surface tappable action chips to the client.

Owning the loop makes those four straightforward.

### Flow

```python
for round in range(MAX_TOOL_ROUNDS):        # 6
    result = await ai_client.complete(history, system=system, tools=tools)
    if result.is_refusal:
        return polite_decline_in_user_language()

    history.append({"role": "assistant", "content": result.content})
    if not result.tool_uses:
        break

    results = [await executor.run(call["name"], call["input"]) for call in result.tool_uses]
    # All results for a parallel batch go back in ONE user message —
    # splitting them trains the model to stop batching.
    history.append({"role": "user", "content": results})
```

### Tools

Reads: `search_parties` · `get_party_details` · `search_items` · `get_stock_report` ·
`get_business_summary` · `list_invoices` · `get_outstanding` · `get_top_items`

Writes: `create_party` · `create_item` · `create_invoice` · `record_payment` ·
`record_expense` · `adjust_stock` · `update_item_price`

Each one calls the same service the REST API calls. There is no shortcut path into
the database: an AI-created invoice moves stock, updates the party ledger and writes
an audit row exactly like a hand-typed one, and is marked `source = 'ai'`.

**Descriptions state *when* to call, not just what the tool does** — that measurably
raises the should-call rate on recent models:

```python
"description": (
    "Find customers or suppliers by name or phone. Call this before creating any "
    "invoice or payment for a named person, so you reuse the existing party "
    "instead of creating a duplicate."
)
```

### Permission gating

```python
available_tools(role, allow_writes=True)   # filters the list before the model sees it
```

A salesman's request never contains `adjust_stock`. The model cannot call what it was
not offered, and `ToolExecutor.run` re-checks the permission anyway.

### Name resolution

"ahmad traders" has to reach *Ahmed Traders (Lahore)*. `utils/strings.similarity`
combines a sequence ratio, a substring bonus and token Jaccard; ≥0.80 is treated as
the same party, below that the assistant asks.

### Prompt design

`app/ai/prompts.py` splits the system prompt in two:

```python
[
  {"type": "text", "text": stable_rules, "cache_control": {"type": "ephemeral"}},
  {"type": "text", "text": business_context},   # changes per business/day
]
```

The stable half is cached across every turn and every user of the business; the
volatile half sits after the breakpoint so it never invalidates the cache.

The rules themselves are shaped around one user: a shopkeeper mid-sale.

* **Act, don't ask.** One clarifying question per turn at most, with a best guess inside it.
* **Reply in the language you were written to** — Roman Urdu in, Roman Urdu out.
* **Never invent data.** If a lookup returns nothing, say so.
* **Report the outcome, then stop.**

### Model settings

```python
model="openai/gpt-oss-120b"
max_completion_tokens=4096
reasoning_effort="medium"    # low | medium | high
```

Three things worth knowing:

* **Not every Groq model can call tools.** `llama-3.3-70b-versatile` returns
  `tool_use_failed` on the very prompt this app is built around. `gpt-oss-120b` and
  `qwen/qwen3.6-27b` both handle it, including in Roman Urdu. The model is not a
  free choice — swap it only after testing a tool call.
* **Structured output is strict.** Groq requires every key in `properties` to also
  appear in `required`, at every nesting level, with `additionalProperties: false`.
  Optionality is expressed as `{"type": ["string", "null"]}` instead. `strictify()`
  in `client.py` rewrites any schema to satisfy this, so a new extraction schema
  cannot fail validation on its first real call.
* **The budget is per minute.** ~8,000 tokens/minute on the free tier, and a full
  assistant turn costs 2–4k. The client honours `retry-after` on a 429, retries
  once, and logs `ai.budget_low` as the remaining budget drops.

### Refusals

A content filter can decline a request; that arrives as `finish_reason:
"content_filter"`, which normalises to `stop_reason: "refusal"`.
`AiResult.is_refusal` is
checked **before** reading content, and the user gets a polite line in their own
language rather than a stack trace.

### Long conversations

Past 40 messages the older turns are summarised by the fast model into
`AiConversation.summary` and replayed as a single preamble, so a long chat stays
inside budget without losing names, amounts or an unresolved request.

### Quotas

`AiUsage` rolls tokens up per business per day. `BusinessSettings.ai_monthly_token_cap`
is enforced before each call; over the cap returns `ai_quota_exceeded` rather than a
surprise bill.

---

## OCR

Vision plus **structured outputs** — a JSON schema on the request, so the model
returns a validated object instead of prose someone has to parse.

```python
await ai_client.vision(
    images=[(media_type, raw_bytes)],
    prompt=EXTRACT_PROMPT,
    system=OCR_SYSTEM,
    output_schema=EXTRACT_SCHEMA,
    effort="high",
)
```

The schema makes **every field nullable** on purpose: a null is a correct answer, a
guess is not. The prompt asks the model to check its own arithmetic
(lines → subtotal → total) and describe any mismatch in `notes` rather than
"fixing" the printed figures.

Nothing reaches the ledger automatically. The result is an `ocr_jobs` row with
per-field confidence and warnings; `/ai/ocr/apply` turns the reviewed draft into a
purchase bill or an expense, and the app shows the extraction next to the photo so
the shopkeeper can compare.

Handwritten and mixed Urdu/English bills are explicitly in scope — the prompt tells
the model to transcribe names as written and transliterate only when the rest of the
document is Roman.

---

## Insights

The model never computes anything. `InsightService.collect()` assembles real figures
from the report service — totals, per-item margins with period-over-period change,
ageing buckets, slowest payers, low stock — and the model only interprets them.

The prompt is explicit about what good looks like:

> Good: "Sugar profit dropped to 4% this month (was 11%) — purchase rate went up to
> Rs 142 but you're still selling at Rs 148."
>
> Bad: "Consider reviewing your pricing strategy for optimal margin performance."

Every insight must cite a number that appears in the data, and `metric_used` records
which one. If nothing is notable, the model is told to say so rather than manufacture
a finding.

**With no API key**, `_rule_based()` produces deterministic insights from the same
figures — overdue invoices, low stock, a sales swing over ±15%, a thin net margin —
so the dashboard is never empty.

---

## Staying inside the budget

On Groq's free tier the money cost is zero, so what is actually scarce is the
per-minute token budget. Every lever below buys headroom in that window:

| Lever | Effect |
|---|---|
| Role-filtered tools | A salesman's request carries fewer tool schemas — the single largest slice of input |
| `AI_EFFORT` | Quality ↔ tokens dial; `medium` is a good default |
| Fast model for utility calls | Summarisation uses `llama-3.1-8b-instant` |
| Conversation summarisation | Long chats stop replaying full history |
| `ai_monthly_token_cap` | Hard per-business ceiling, enforced before the call |
| Slim tool results | Tools return formatted strings, not raw ORM dumps |
| Ordered system prompt | Invariant rules first, so a provider with prefix caching benefits for free |

`GET /ai/usage` reports the month's tokens and request count. The cost column reads
zero while `AI_INPUT_COST_PER_MTOK` / `AI_OUTPUT_COST_PER_MTOK` are 0 — set them if
you move to a paid tier and the same meter starts reporting money.
