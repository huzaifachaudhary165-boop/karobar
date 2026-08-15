"""Tool definitions and the dispatcher that runs them against real services.

Every write the assistant performs goes through the same services the REST API
uses — same validation, same stock movements, same audit trail. There is no
"AI shortcut" path into the database.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import log
from app.core.money import ZERO, D, format_money, money
from app.core.pagination import PageParams
from app.core.permissions import Perm, has_permission
from app.models.ai import AiToolCall
from app.models.enums import PartyType, PaymentDirection, VoucherType
from app.schemas.item import ItemCreate
from app.schemas.party import PartyCreate
from app.schemas.payment import ExpenseCreate, PaymentCreate
from app.schemas.voucher import (
    PaymentInline, ShareRequest, VoucherCreate, VoucherLineInput,
)
from app.services.base import ActorContext
from app.services.expense_service import ExpenseService
from app.services.item_service import ItemService, StockService
from app.services.party_service import PartyService
from app.services.payment_service import PaymentService
from app.services.report_service import ReportService
from app.services.share_service import ShareService
from app.services.voucher_service import VoucherService
from app.utils.dates import resolve_period

# ── schemas ──────────────────────────────────────────────────────
_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string"},
        "qty": {"type": "number", "minimum": 0},
        "rate": {"type": "number", "description": "Per unit. Omit for the saved price."},
        "discount_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "tax_rate": {"type": "number", "description": "Omit for the item's own rate."},
    },
    "required": ["item", "qty"],
    "additionalProperties": False,
}

TOOLS: list[dict[str, Any]] = [
    # ── read ─────────────────────────────────────────────────────
    {
        "name": "search_parties",
        "description": (
            "Look up a customer/supplier — balance, phone. For *questions* about someone. "
            "Writing tools resolve names themselves, so do not call this before them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or phone number to look for."},
                "party_type": {"type": "string", "enum": ["customer", "supplier", "all"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_party_details",
        "description": (
            "One party in full: balance, credit limit, recent bills. Use for 'kitna baqi hai'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "party_name": {"type": "string"},
                "include_ledger": {"type": "boolean", "description": "Include recent entries."},
            },
            "required": ["party_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_items",
        "description": (
            "Look up items — price, stock, tax. For *questions*, or to quote a price before "
            "billing. create_invoice resolves item names itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_stock_report",
        "description": (
            "Stock position: value, low and out-of-stock. 'Kya khatam ho raha hai'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "only_low_stock": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_business_summary",
        "description": (
            "Sales, purchases, expenses, profit, receivables and cash for a period, vs the "
            "previous one. 'Aaj ki sale', 'is mahine ka hisab'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": [
                        "today", "yesterday", "this_week", "last_week", "this_month",
                        "last_month", "this_quarter", "this_year", "last_7_days",
                        "last_30_days", "fy",
                    ],
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_invoices",
        "description": (
            "List documents with filters. 'Aaj ke bills', 'unpaid invoices', or to find one "
            "before sharing or settling it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "voucher_type": {
                    "type": "string",
                    "enum": ["sale", "purchase", "quotation", "sale_return", "purchase_return"],
                },
                "party_name": {"type": "string"},
                "period": {"type": "string"},
                "only_unpaid": {"type": "boolean"},
                "only_overdue": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_outstanding",
        "description": (
            "Who owes money and who is owed, by how overdue. 'Kitna udhaar hai'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["receivable", "payable"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_top_items",
        "description": (
            "Best sellers for a period with revenue and profit. 'Sabse zyada kya bika'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "additionalProperties": False,
        },
    },
    # ── write ────────────────────────────────────────────────────
    {
        "name": "create_party",
        "description": (
            "Add a new customer or supplier. Call search_parties first — only create when there "
            "is genuinely no match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "party_type": {"type": "string", "enum": ["customer", "supplier", "both"]},
                "phone": {"type": "string"},
                "opening_balance": {
                    "type": "number",
                    "description": "Existing dues. Positive = they owe us.",
                },
                "address": {"type": "string"},
                "credit_limit": {"type": "number"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_item",
        "description": (
            "Add a new product or service to the catalogue. Call search_items first so you do "
            "not create a duplicate of an existing item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "sale_price": {"type": "number"},
                "purchase_price": {"type": "number"},
                "opening_stock": {"type": "number"},
                "unit": {"type": "string", "description": "e.g. Pcs, Kg, Bag, Litre"},
                "tax_rate": {"type": "number", "minimum": 0, "maximum": 100},
                "low_stock_qty": {"type": "number"},
                "item_type": {"type": "string", "enum": ["product", "service"]},
            },
            "required": ["name", "sale_price"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_invoice",
        "description": (
            "Create a sale, purchase, quotation or return. Resolves party and item names "
            "itself — call it directly, no lookup first. Set paid_amount if paid now."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "voucher_type": {
                    "type": "string",
                    "enum": ["sale", "purchase", "quotation", "sale_return", "purchase_return"],
                },
                "party_name": {"type": "string", "description": "Customer or supplier name."},
                "lines": {"type": "array", "items": _LINE_SCHEMA, "minItems": 1},
                "voucher_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
                "discount_amount": {"type": "number", "description": "Whole-invoice discount."},
                "paid_amount": {
                    "type": "number",
                    "description": "Amount paid immediately. Omit for full credit.",
                },
                "payment_mode": {
                    "type": "string",
                    "enum": ["cash", "bank", "upi", "card", "cheque", "easypaisa", "jazzcash"],
                },
                "notes": {"type": "string"},
            },
            "required": ["voucher_type", "lines"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_payment",
        "description": (
            "Record money in or out. Settles the oldest bills first. 'Ahmed ne 5000 diye'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "party_name": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
                "direction": {
                    "type": "string",
                    "enum": ["in", "out"],
                    "description": "'in' = received from customer, 'out' = paid to supplier.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["cash", "bank", "upi", "card", "cheque", "easypaisa", "jazzcash"],
                },
                "payment_date": {"type": "string", "description": "YYYY-MM-DD."},
                "reference_number": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["party_name", "amount"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_expense",
        "description": (
            "Log a business expense — rent, salary, transport, tea, utilities. Call this for "
            "'kharcha likho', 'expense add karo'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
                "category": {"type": "string", "description": "e.g. Rent, Salaries, Transport"},
                "expense_date": {"type": "string", "description": "YYYY-MM-DD."},
                "payment_mode": {"type": "string", "enum": ["cash", "bank", "upi", "cheque"]},
                "vendor_name": {"type": "string"},
            },
            "required": ["title", "amount"],
            "additionalProperties": False,
        },
    },
    {
        "name": "adjust_stock",
        "description": (
            "Correct an item's stock without an invoice — damage, theft, wastage, or a physical "
            "count. Use a negative quantity to reduce."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string"},
                "qty_change": {
                    "type": "number",
                    "description": "Signed: +10 adds ten, -3 removes three.",
                },
                "reason": {"type": "string"},
            },
            "required": ["item_name", "qty_change", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_item_price",
        "description": "Change an item's selling and/or purchase price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string"},
                "sale_price": {"type": "number"},
                "purchase_price": {"type": "number"},
            },
            "required": ["item_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "share_invoice",
        "description": (
            "Send an invoice on WhatsApp, email or SMS, or get a link. Omit the number for "
            "the latest one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {
                    "type": "string",
                    "description": "e.g. INV-2026-27/0001. Omit to use the most recent invoice.",
                },
                "channel": {"type": "string", "enum": ["whatsapp", "email", "sms", "link"]},
                "message": {"type": "string", "description": "Optional note to send with it."},
            },
            "required": ["channel"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_invoice",
        "description": (
            "Cancel an invoice — reverses stock and balance, keeps the record. Confirm first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["invoice_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_invoice",
        "description": (
            "Delete a bill that should never have existed — a duplicate, a test entry, "
            "a slip of the hand. It goes for good and leaves no record. "
            "If the sale really happened and was returned, use cancel_invoice instead: "
            "that keeps the bill in the books so the customer's copy can be matched "
            "against it. Always ask the user to confirm before calling this, and say "
            "which of the two you are about to do."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
            },
            "required": ["invoice_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_invoice",
        "description": (
            "Correct a bill that is already saved — a wrong quantity, rate or date. "
            "Give only what changes; anything left out stays as it is. Lines given "
            "replace all the lines on the bill, so include every line you want kept. "
            "Stock and the customer balance are re-worked to match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
                "lines": {"type": "array", "items": _LINE_SCHEMA},
                "voucher_date": {"type": "string", "description": "YYYY-MM-DD."},
                "notes": {"type": "string"},
            },
            "required": ["invoice_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_party",
        "description": (
            "Remove a customer or supplier. Refused while they have bills or payments "
            "against them. Ask the user to confirm first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"party_name": {"type": "string"}},
            "required": ["party_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_item",
        "description": (
            "Remove an item from the shop's list. Refused while it appears on bills — "
            "mark it inactive instead. Ask the user to confirm first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"item_name": {"type": "string"}},
            "required": ["item_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_party",
        "description": (
            "Change a party's phone, email, address or credit limit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "party_name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
                "credit_limit": {"type": "number"},
            },
            "required": ["party_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_party_ledger",
        "description": (
            "Running statement for one party. Use for 'Ahmed ka hisaab dikhao'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "party_name": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["party_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_profit_report",
        "description": (
            "Profit and loss for a period. Use for 'profit kitna hua'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": [
                        "today", "this_week", "this_month", "last_month",
                        "this_quarter", "this_year", "last_7_days", "last_30_days",
                    ],
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}

WRITE_TOOLS = {
    "create_party", "create_item", "create_invoice", "record_payment",
    "record_expense", "adjust_stock", "update_item_price",
    "share_invoice", "cancel_invoice", "update_party",
    "update_invoice", "delete_invoice", "delete_party", "delete_item",
}

# Nothing here can be undone by asking again. The assistant is told to confirm
# before calling any of them, and the app shows what happened afterwards — but
# the real protection is that each one is refused by the service underneath
# when the record is still referenced by something else.
DESTRUCTIVE_TOOLS = {"delete_invoice", "delete_party", "delete_item"}

TOOL_PERMISSION: dict[str, Perm] = {
    "search_parties": Perm.PARTY_READ,
    "get_party_details": Perm.PARTY_READ,
    "search_items": Perm.ITEM_READ,
    "get_stock_report": Perm.ITEM_READ,
    "get_business_summary": Perm.REPORT_READ,
    "list_invoices": Perm.SALE_READ,
    "get_outstanding": Perm.REPORT_READ,
    "get_top_items": Perm.REPORT_READ,
    "create_party": Perm.PARTY_WRITE,
    "create_item": Perm.ITEM_WRITE,
    "create_invoice": Perm.SALE_WRITE,
    "record_payment": Perm.PAYMENT_WRITE,
    "record_expense": Perm.EXPENSE_WRITE,
    "adjust_stock": Perm.STOCK_ADJUST,
    "update_item_price": Perm.ITEM_WRITE,
    "share_invoice": Perm.SALE_READ,
    "cancel_invoice": Perm.SALE_WRITE,
    "update_invoice": Perm.SALE_WRITE,
    "delete_invoice": Perm.SALE_DELETE,
    "delete_party": Perm.PARTY_DELETE,
    "delete_item": Perm.ITEM_DELETE,
    "update_party": Perm.PARTY_WRITE,
    "get_party_ledger": Perm.PARTY_READ,
    "get_profit_report": Perm.REPORT_READ,
}

# Deep links the app opens when the user taps an action chip.
DEEP_LINK: dict[str, str] = {
    "create_invoice": "/invoices/{id}",
    "share_invoice": "/invoices/{id}",
    "cancel_invoice": "/invoices/{id}",
    "update_invoice": "/invoices/{id}",
    "update_party": "/parties/{id}",
    "get_party_ledger": "/parties/{id}",
    "record_payment": "/payments/{id}",
    "record_expense": "/expenses/{id}",
    "create_party": "/parties/{id}",
    "create_item": "/items/{id}",
    "adjust_stock": "/items/{id}",
    "update_item_price": "/items/{id}",
}


def available_tools(role: str | None, *, allow_writes: bool = True) -> list[dict[str, Any]]:
    """Only advertise tools this role may actually run — the model never sees the rest."""
    out = []
    for tool in TOOLS:
        name = tool["name"]
        if not allow_writes and name in WRITE_TOOLS:
            continue
        perm = TOOL_PERMISSION.get(name)
        if role and perm and not has_permission(role, perm):
            continue
        out.append(tool)
    return out


class ToolExecutor:
    """Runs a tool call and returns a JSON-serialisable result for the model."""

    def __init__(self, db: AsyncSession, actor: ActorContext, *, currency: str = "Rs") -> None:
        self.db = db
        self.actor = actor
        self.currency = currency
        self.parties = PartyService(db, actor)
        self.items = ItemService(db, actor)
        self.vouchers = VoucherService(db, actor)
        self.payments = PaymentService(db, actor)
        self.expenses = ExpenseService(db, actor)
        self.stock = StockService(db, actor)
        self.reports = ReportService(db, actor)
        self.sharing = ShareService(db, actor)

    async def run(
        self, name: str, arguments: dict[str, Any], *, conversation_id: str | None = None
    ) -> dict[str, Any]:
        started = time.perf_counter()
        entity_type: str | None = None
        entity_id: str | None = None
        success = True
        error: str | None = None

        try:
            if name not in TOOL_NAMES:
                raise AppError(f"Unknown tool '{name}'.", code="unknown_tool")

            perm = TOOL_PERMISSION.get(name)
            if perm and self.actor.role and not has_permission(self.actor.role, perm):
                raise AppError(
                    f"Your role ({self.actor.role}) is not allowed to do that.",
                    code="forbidden",
                )

            handler = getattr(self, f"_t_{name}")
            result = await handler(arguments)
            entity_type = result.pop("_entity_type", None)
            entity_id = result.pop("_entity_id", None)

        except AppError as exc:
            success, error = False, exc.message
            result = {"ok": False, "error": exc.message, "code": exc.code, **exc.details}
        except Exception as exc:  # noqa: BLE001 — never let a tool crash the chat turn
            log.exception("ai.tool_failed", tool=name, error=str(exc))
            success, error = False, str(exc)
            result = {"ok": False, "error": "That action could not be completed."}

        duration = int((time.perf_counter() - started) * 1000)
        self.db.add(
            AiToolCall(
                business_id=self.actor.business_id,
                conversation_id=conversation_id,
                user_id=self.actor.user_id,
                tool_name=name,
                arguments=_jsonable(arguments),
                result=_jsonable(result),
                is_write=name in WRITE_TOOLS,
                success=success,
                error=error,
                duration_ms=duration,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
        result.setdefault("ok", success)
        if entity_id:
            result["_meta"] = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "deep_link": DEEP_LINK.get(name, "").format(id=entity_id) or None,
            }
        return result

    # ── read handlers ────────────────────────────────────────────
    async def _t_search_parties(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = await self.parties.search_by_name(args["query"], limit=args.get("limit", 5))
        ptype = args.get("party_type", "all")
        rows = [
            {
                "name": p.name,
                "type": p.party_type,
                "phone": p.phone,
                "balance": self._fmt(p.balance),
                "owes_us": p.balance > 0,
                "match_confidence": round(score, 2),
            }
            for p, score in matches
            if ptype == "all" or p.party_type in (ptype, PartyType.BOTH)
        ]
        return {"count": len(rows), "parties": rows}

    async def _t_get_party_details(self, args: dict[str, Any]) -> dict[str, Any]:
        party = await self._resolve_party(args["party_name"], create=False)
        if party is None:
            return {"found": False, "message": f"No party named '{args['party_name']}'."}

        unpaid = await self.vouchers.outstanding_for_party(
            party.id, direction="receivable" if party.balance >= 0 else "payable"
        )
        out: dict[str, Any] = {
            "found": True,
            "name": party.name,
            "type": party.party_type,
            "phone": party.phone,
            "balance": self._fmt(party.balance),
            "balance_meaning": (
                "they owe us" if party.balance > 0
                else "we owe them" if party.balance < 0
                else "settled"
            ),
            "credit_limit": self._fmt(party.credit_limit) if party.credit_limit else None,
            "over_credit_limit": party.is_over_credit_limit,
            "total_sales": self._fmt(party.total_sales),
            "transaction_count": party.transaction_count,
            "unpaid_invoices": [
                {
                    "number": v.number,
                    "date": v.voucher_date.isoformat(),
                    "total": self._fmt(v.total),
                    "due": self._fmt(v.balance_amount),
                    "days_overdue": v.days_overdue,
                }
                for v in unpaid[:10]
            ],
        }
        if args.get("include_ledger"):
            ledger = await self.parties.ledger(party.id)
            out["recent_entries"] = [
                {
                    "date": e.date.isoformat(),
                    "description": e.description,
                    "debit": self._fmt(e.debit),
                    "credit": self._fmt(e.credit),
                    "balance": self._fmt(e.balance),
                }
                for e in ledger["entries"][-10:]
            ]
        return out

    async def _t_search_items(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = await self.items.search_by_name(args["query"], limit=args.get("limit", 5))
        return {
            "count": len(matches),
            "items": [
                {
                    "name": i.name,
                    "sale_price": self._fmt(i.sale_price),
                    "purchase_price": self._fmt(i.purchase_price),
                    "stock": str(i.stock_qty),
                    "unit": i.unit_label,
                    "tax_rate": str(i.tax_rate),
                    "low_stock": i.is_low_stock,
                    "match_confidence": round(score, 2),
                }
                for i, score in matches
            ],
        }

    async def _t_get_stock_report(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = await self.items.stock_summary()
        low = await self.items.low_stock_items(limit=args.get("limit", 20))
        out = {
            "total_items": summary["total_items"],
            "total_stock_value": self._fmt(summary["total_stock_value"]),
            "low_stock_count": summary["low_stock_count"],
            "out_of_stock_count": summary["out_of_stock_count"],
            "expiring_soon_count": summary["expiring_soon_count"],
            "low_stock_items": [
                {
                    "name": i.name,
                    "stock": str(i.stock_qty),
                    "unit": i.unit_label,
                    "reorder_at": str(i.low_stock_qty),
                }
                for i in low
            ],
        }
        if not args.get("only_low_stock"):
            out["highest_value_items"] = [
                {"name": i.name, "stock": str(i.stock_qty), "value": self._fmt(i.stock_value)}
                for i in summary["top_value_items"][:5]
            ]
        return out

    async def _t_get_business_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        data = await self.reports.dashboard(args.get("period", "today"))
        return {
            "period": data["period_label"],
            "from": data["start_date"].isoformat(),
            "to": data["end_date"].isoformat(),
            "sales": self._trend(data["sales"]),
            "purchases": self._trend(data["purchases"]),
            "expenses": self._trend(data["expenses"]),
            "net_profit": self._trend(data["profit"]),
            "money_collected": self._trend(data["collections"]),
            "receivable": self._fmt(data["receivable"]),
            "payable": self._fmt(data["payable"]),
            "cash_in_hand": self._fmt(data["cash_in_hand"]),
            "bank_balance": self._fmt(data["bank_balance"]),
            "stock_value": self._fmt(data["stock_value"]),
            "invoice_count": data["invoice_count"],
            "unpaid_invoice_count": data["unpaid_invoice_count"],
            "overdue_amount": self._fmt(data["overdue_amount"]),
            "low_stock_count": data["low_stock_count"],
        }

    async def _t_list_invoices(self, args: dict[str, Any]) -> dict[str, Any]:
        party_id = None
        if args.get("party_name"):
            party = await self._resolve_party(args["party_name"], create=False)
            if party is None:
                return {"count": 0, "invoices": [], "note": f"No party '{args['party_name']}'."}
            party_id = party.id

        start = end = None
        if args.get("period"):
            start, end = resolve_period(args["period"])

        rows, total = await self.vouchers.list(
            PageParams(page=1, size=args.get("limit", 15)),
            voucher_type=args.get("voucher_type", VoucherType.SALE),
            party_id=party_id,
            start_date=start,
            end_date=end,
            only_unpaid=args.get("only_unpaid", False),
            only_overdue=args.get("only_overdue", False),
        )
        return {
            "count": total,
            "showing": len(rows),
            "invoices": [
                {
                    "number": v.number,
                    "date": v.voucher_date.isoformat(),
                    "party": v.party_name,
                    "total": self._fmt(v.total),
                    "paid": self._fmt(v.paid_amount),
                    "due": self._fmt(v.balance_amount),
                    "status": v.status,
                    "items": len(v.lines),
                }
                for v in rows
            ],
        }

    async def _t_get_outstanding(self, args: dict[str, Any]) -> dict[str, Any]:
        receivable = args.get("direction", "receivable") == "receivable"
        data = await self.parties.ageing(receivable=receivable)
        limit = args.get("limit", 15)
        return {
            "direction": data["direction"],
            "total": self._fmt(data["total"]),
            "buckets": [
                {"period": b["label"], "amount": self._fmt(b["amount"]), "invoices": b["count"]}
                for b in data["buckets"]
            ],
            "parties": [
                {
                    "name": p["party_name"],
                    "amount": self._fmt(p["total"]),
                    "invoices": p["invoice_count"],
                    "oldest_due": p["oldest_due_date"].isoformat(),
                }
                for p in data["parties"][:limit]
            ],
        }

    async def _t_get_top_items(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end = resolve_period(args.get("period", "this_month"))
        rows = await self.reports.top_items(start, end, limit=args.get("limit", 10))
        return {
            "period": f"{start.isoformat()} to {end.isoformat()}",
            "items": [
                {
                    "name": r["name"],
                    "quantity_sold": str(r["quantity"]),
                    "revenue": self._fmt(r["revenue"]),
                    "profit": self._fmt(r["profit"]),
                    "times_sold": r["sale_count"],
                }
                for r in rows
            ],
        }

    # ── write handlers ───────────────────────────────────────────
    async def _t_create_party(self, args: dict[str, Any]) -> dict[str, Any]:
        party = await self.parties.create(
            PartyCreate(
                name=args["name"],
                party_type=args.get("party_type", PartyType.CUSTOMER),
                phone=args.get("phone"),
                billing_address=args.get("address"),
                opening_balance=money(args.get("opening_balance", 0)),
                credit_limit=money(args["credit_limit"]) if args.get("credit_limit") else None,
            )
        )
        return {
            "created": True,
            "name": party.name,
            "type": party.party_type,
            "balance": self._fmt(party.balance),
            "_entity_type": "party",
            "_entity_id": party.id,
        }

    async def _t_create_item(self, args: dict[str, Any]) -> dict[str, Any]:
        item = await self.items.create(
            ItemCreate(
                name=args["name"],
                item_type=args.get("item_type", "product"),
                sale_price=money(args["sale_price"]),
                purchase_price=money(args.get("purchase_price", 0)),
                unit_label=args.get("unit", "Pcs"),
                tax_rate=money(args.get("tax_rate", 0)),
                low_stock_qty=D(args["low_stock_qty"]) if args.get("low_stock_qty") else None,
                opening_stock=D(args.get("opening_stock", 0)),
                opening_stock_value=money(
                    D(args.get("opening_stock", 0)) * D(args.get("purchase_price", 0))
                ),
            )
        )
        return {
            "created": True,
            "name": item.name,
            "sale_price": self._fmt(item.sale_price),
            "stock": str(item.stock_qty),
            "_entity_type": "item",
            "_entity_id": item.id,
        }

    async def _t_create_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        vtype = VoucherType(args.get("voucher_type", VoucherType.SALE))
        party = None
        if args.get("party_name"):
            party = await self._resolve_party(args["party_name"], party_type=vtype.party_kind)

        lines: list[VoucherLineInput] = []
        created_items: list[str] = []
        for raw in args["lines"]:
            item, was_created = await self.items.resolve_or_create(
                raw["item"],
                sale_price=money(raw.get("rate", 0)),
                purchase_price=money(raw.get("rate", 0)) if vtype.party_kind == "supplier" else None,
            )
            if was_created:
                created_items.append(item.name)
            lines.append(
                VoucherLineInput(
                    item_id=item.id,
                    item_name=item.name,
                    qty=D(raw["qty"]),
                    rate=money(raw["rate"]) if raw.get("rate") is not None else money(
                        item.purchase_price if vtype.party_kind == "supplier" else item.sale_price
                    ),
                    discount_value=money(raw.get("discount_percent", 0)),
                    tax_rate=money(raw["tax_rate"]) if raw.get("tax_rate") is not None else None,
                )
            )

        payment = None
        if args.get("paid_amount"):
            payment = PaymentInline(
                amount=money(args["paid_amount"]), mode=args.get("payment_mode", "cash")
            )

        voucher = await self.vouchers.create(
            VoucherCreate(
                voucher_type=vtype,
                party_id=party.id if party else None,
                party_name=party.name if party else args.get("party_name"),
                voucher_date=_parse_date(args.get("voucher_date")),
                lines=lines,
                discount_value=money(args.get("discount_amount", 0)),
                notes=args.get("notes"),
                payment=payment,
                source="ai",
            )
        )
        await self.db.refresh(voucher)
        return {
            "created": True,
            "number": voucher.number,
            "type": voucher.voucher_type,
            "party": voucher.party_name,
            "date": voucher.voucher_date.isoformat(),
            "line_count": len(voucher.lines),
            "subtotal": self._fmt(voucher.subtotal),
            "tax": self._fmt(voucher.tax_amount),
            "total": self._fmt(voucher.total),
            "paid": self._fmt(voucher.paid_amount),
            "balance_due": self._fmt(voucher.balance_amount),
            "new_items_created": created_items or None,
            "_entity_type": "voucher",
            "_entity_id": voucher.id,
        }

    async def _t_record_payment(self, args: dict[str, Any]) -> dict[str, Any]:
        direction = args.get("direction") or PaymentDirection.IN
        party = await self._resolve_party(
            args["party_name"],
            party_type="customer" if direction == PaymentDirection.IN else "supplier",
        )
        result = await self.payments.settle_party(
            party.id,
            money(args["amount"]),
            direction=direction,
            mode=args.get("mode", "cash"),
            payment_date=_parse_date(args.get("payment_date")),
            notes=args.get("notes"),
            source="ai",
        )
        payment = result["payment"]
        return {
            "recorded": True,
            "receipt_number": payment.number,
            "party": party.name,
            "amount": self._fmt(payment.amount),
            "direction": "received" if direction == PaymentDirection.IN else "paid",
            "settled_invoices": [
                {"number": s["voucher_number"], "amount": self._fmt(s["amount"])}
                for s in result["settled_vouchers"]
            ],
            "advance_remaining": self._fmt(result["remaining_credit"]),
            "party_balance_now": self._fmt(result["party_balance_after"]),
            "_entity_type": "payment",
            "_entity_id": payment.id,
        }

    async def _t_record_expense(self, args: dict[str, Any]) -> dict[str, Any]:
        expense = await self.expenses.create(
            ExpenseCreate(
                title=args["title"],
                amount=money(args["amount"]),
                category_name=args.get("category"),
                expense_date=_parse_date(args.get("expense_date")),
                payment_mode=args.get("payment_mode", "cash"),
                vendor_name=args.get("vendor_name"),
                source="ai",
            )
        )
        return {
            "recorded": True,
            "number": expense.number,
            "title": expense.title,
            "category": expense.category_name,
            "amount": self._fmt(expense.total),
            "date": expense.expense_date.isoformat(),
            "_entity_type": "expense",
            "_entity_id": expense.id,
        }

    async def _t_adjust_stock(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = await self.items.search_by_name(args["item_name"], limit=1)
        if not matches:
            raise AppError(f"No item named '{args['item_name']}'.", code="not_found")
        item = matches[0][0]
        before = item.stock_qty
        await self.stock.adjust(item.id, qty_delta=D(args["qty_change"]), reason=args["reason"])
        return {
            "adjusted": True,
            "item": item.name,
            "before": str(before),
            "change": str(D(args["qty_change"])),
            "after": str(item.stock_qty),
            "reason": args["reason"],
            "_entity_type": "item",
            "_entity_id": item.id,
        }

    async def _t_update_item_price(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = await self.items.search_by_name(args["item_name"], limit=1)
        if not matches:
            raise AppError(f"No item named '{args['item_name']}'.", code="not_found")
        item = matches[0][0]
        old_sale, old_purchase = item.sale_price, item.purchase_price

        updates: dict[str, Any] = {}
        if args.get("sale_price") is not None:
            updates["sale_price"] = money(args["sale_price"])
        if args.get("purchase_price") is not None:
            updates["purchase_price"] = money(args["purchase_price"])
        if not updates:
            raise AppError("Provide a new sale price or purchase price.", code="validation_error")

        await self.items.update(item.id, updates)
        return {
            "updated": True,
            "item": item.name,
            "sale_price": {"before": self._fmt(old_sale), "after": self._fmt(item.sale_price)},
            "purchase_price": {
                "before": self._fmt(old_purchase),
                "after": self._fmt(item.purchase_price),
            },
            "_entity_type": "item",
            "_entity_id": item.id,
        }

    # ── documents ────────────────────────────────────────────────
    async def _t_share_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        voucher = await self._resolve_voucher(args.get("invoice_number"))
        result = await self.sharing.share_voucher(
            voucher.id,
            ShareRequest(channel=args["channel"], message=args.get("message")),
        )
        # A share_url means the channel is not connected: the server produced a
        # link for the user to open, it did not deliver anything. Reporting that
        # as "sent" would leave a shopkeeper believing their customer has the
        # bill, so `delivered` is stated separately and the model is told what
        # to say instead.
        delivered = bool(result.get("success")) and not result.get("share_url")
        return {
            "ok": bool(result.get("success", True)),
            "number": voucher.number,
            "party": voucher.party_name,
            "channel": result.get("channel", args["channel"]),
            "delivered": delivered,
            "sent_to": result.get("recipient"),
            "share_url": result.get("share_url"),
            "detail": result.get("detail"),
            "next_step": None
            if delivered
            else (
                "NOT sent yet. Tell the user to tap the action chip to open "
                f"{args['channel']} and send it themselves."
            ),
            "_entity_type": "voucher",
            "_entity_id": voucher.id,
        }

    async def _t_cancel_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        voucher = await self._resolve_voucher(args["invoice_number"])
        cancelled = await self.vouchers.cancel(voucher.id, args.get("reason"))
        return {
            "number": cancelled.number,
            "party": cancelled.party_name,
            "total": self._fmt(cancelled.total),
            "status": cancelled.status,
            "note": "Stock and the party balance have been reversed.",
            "_entity_type": "voucher",
            "_entity_id": cancelled.id,
        }

    async def _t_delete_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        voucher = await self._resolve_voucher(args["invoice_number"])
        number, total = voucher.number, voucher.total
        await self.vouchers.delete(voucher.id)
        return {
            "deleted": number,
            "total": self._fmt(total),
            "note": (
                "Gone for good — no record it existed. Stock and the party "
                "balance are back where they were."
            ),
        }

    async def _t_update_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.schemas.voucher import VoucherUpdate

        voucher = await self._resolve_voucher(args["invoice_number"])

        changes: dict[str, Any] = {}
        if args.get("voucher_date"):
            changes["voucher_date"] = date.fromisoformat(args["voucher_date"])
        if args.get("notes") is not None:
            changes["notes"] = args["notes"]
        if args.get("lines"):
            rebuilt: list[VoucherLineInput] = []
            for raw in args["lines"]:
                # Resolved, never created. A correction that quietly invents an
                # item because the name was misheard makes the bill worse than
                # it already was.
                matches = await self.items.search_by_name(raw["item"], limit=1)
                item = matches[0][0] if matches and matches[0][1] >= 0.85 else None
                if item is None:
                    raise AppError(
                        f"No item called '{raw['item']}'. Add it first, or "
                        "check the spelling.",
                        code="not_found",
                    )
                rebuilt.append(
                    VoucherLineInput(
                        item_id=item.id,
                        item_name=item.name,
                        qty=D(raw["qty"]),
                        rate=money(raw["rate"])
                        if raw.get("rate") is not None
                        else money(item.sale_price),
                        discount_value=money(raw.get("discount_percent", 0)),
                        tax_rate=money(raw["tax_rate"])
                        if raw.get("tax_rate") is not None
                        else None,
                    )
                )
            changes["lines"] = rebuilt

        if not changes:
            raise AppError(
                "Nothing to change — say what should be different about the bill.",
                code="validation_error",
            )

        updated = await self.vouchers.update(
            voucher.id, VoucherUpdate.model_validate(changes)
        )
        return {
            "number": updated.number,
            "party": updated.party_name,
            "total": self._fmt(updated.total),
            "status": updated.status,
            "note": "Stock and the party balance were re-worked to match.",
            "_entity_type": "voucher",
            "_entity_id": updated.id,
        }

    # ── parties ──────────────────────────────────────────────────
    async def _t_delete_party(self, args: dict[str, Any]) -> dict[str, Any]:
        party = await self._resolve_party(args["party_name"], create=False)
        if party is None:
            raise AppError(
                f"No customer or supplier called '{args['party_name']}'.",
                code="not_found",
            )

        name = party.name
        await self.parties.delete(party.id)
        return {"deleted": name, "note": "Removed from your list."}

    async def _t_delete_item(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = await self.items.search_by_name(args["item_name"], limit=1)
        if not matches or matches[0][1] < 0.85:
            raise AppError(
                f"No item called '{args['item_name']}'.", code="not_found"
            )
        item = matches[0][0]
        name = item.name
        await self.items.delete(item.id)
        return {"deleted": name, "note": "Removed from your items."}

    async def _t_update_party(self, args: dict[str, Any]) -> dict[str, Any]:
        party = await self._resolve_party(args["party_name"], create=False)
        if party is None:
            raise AppError(f"No customer or supplier called '{args['party_name']}'.",
                           code="not_found")

        changes = {
            key: args[key]
            for key in ("phone", "email", "credit_limit")
            if args.get(key) is not None
        }
        if args.get("address"):
            changes["billing_address"] = args["address"]
        if not changes:
            raise AppError("Nothing to change — say what should be updated.",
                           code="validation_error")

        updated = await self.parties.update(party.id, changes)
        return {
            "name": updated.name,
            "updated": sorted(changes),
            "_entity_type": "party",
            "_entity_id": updated.id,
        }

    async def _t_get_party_ledger(self, args: dict[str, Any]) -> dict[str, Any]:
        party = await self._resolve_party(args["party_name"], create=False)
        if party is None:
            return {"found": False, "note": f"No party called '{args['party_name']}'."}

        data = await self.parties.ledger(party.id)
        entries = data["entries"]
        closing = data["closing_balance"]
        # Newest entries are what a question about a running account is about.
        recent = entries[-args.get("limit", 15):]

        return {
            "party": party.name,
            "closing_balance": self._fmt(closing),
            "direction": "they owe you" if closing > 0 else "you owe them",
            "showing": len(recent),
            "of_total": len(entries),
            "entries": [
                {
                    "date": e.date.isoformat(),
                    "description": e.description,
                    "debit": self._fmt(e.debit),
                    "credit": self._fmt(e.credit),
                    "balance": self._fmt(e.balance),
                }
                for e in recent
            ],
        }

    # ── reports ──────────────────────────────────────────────────
    async def _t_get_profit_report(self, args: dict[str, Any]) -> dict[str, Any]:
        period = args.get("period", "this_month")
        start, end = resolve_period(period)
        data = await self.reports.profit_and_loss(start, end)
        return {
            "period": period,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "sales": self._fmt(data.get("net_sales")),
            "cost_of_goods_sold": self._fmt(data.get("cost_of_goods_sold")),
            "gross_profit": self._fmt(data.get("gross_profit")),
            "expenses": self._fmt(data.get("total_expenses")),
            "net_profit": self._fmt(data.get("net_profit")),
            "margin_percent": str(data.get("net_margin_percent") or 0),
        }

    # ── helpers ──────────────────────────────────────────────────
    async def _resolve_party(
        self, name: str, *, party_type: str = PartyType.CUSTOMER, create: bool = True
    ):
        matches = await self.parties.search_by_name(name, limit=1)
        if matches and matches[0][1] >= 0.8:
            return matches[0][0]
        if not create:
            return None
        party, _ = await self.parties.resolve_or_create(name, party_type=party_type)
        return party

    async def _resolve_voucher(self, number: str | None):
        """Find an invoice by the number the user said, or take the latest.

        People rarely quote a full document number out loud — "wo pichhla bill"
        means the most recent one, and a partial number like "0042" should still
        land. A wrong match here cancels or sends the wrong invoice, so a partial
        that matches more than one is refused rather than guessed.
        """
        rows, _ = await self.vouchers.list(PageParams(page=1, size=25))
        if not rows:
            raise AppError("There are no invoices yet.", code="not_found")

        if not number:
            return rows[0]

        wanted = number.strip().lower()
        exact = [v for v in rows if v.number.lower() == wanted]
        if exact:
            return exact[0]

        partial = [v for v in rows if wanted in v.number.lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise AppError(
                f"'{number}' matches {len(partial)} invoices — give the full number.",
                code="ambiguous",
                details={"matches": [v.number for v in partial[:5]]},
            )
        raise AppError(f"No invoice numbered '{number}'.", code="not_found")

    def _fmt(self, value: Any) -> str:
        return format_money(value or ZERO, symbol=f"{self.currency} ")

    def _trend(self, trend: dict[str, Any]) -> dict[str, Any]:
        out = {"amount": self._fmt(trend["value"])}
        if trend.get("change_percent") is not None:
            out["change_vs_previous"] = f"{trend['change_percent']}%"
            out["direction"] = trend["direction"]
        return out


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    from app.utils.dates import parse_date  # noqa: PLC0415

    return parse_date(value)


def _jsonable(value: Any) -> Any:
    from app.services.base import _jsonable as coerce  # noqa: PLC0415

    return coerce(value)
