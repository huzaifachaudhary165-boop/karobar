"""Reports beyond the obvious ones."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(start: date | None, end: date | None) -> tuple[date, date]:
    """Default to this month, which is the period a shopkeeper means."""
    finish = end or date.today()
    return start or finish.replace(day=1), finish


@router.get("/dead-stock", summary="Goods that are not selling")
async def dead_stock(
    tenant: Tenant,
    db: DbSession,
    days: int = Query(90, ge=7, le=730),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Sorted by what it is tying up, not by how long it has sat.

    Forty slow items worth two hundred rupees between them is not a problem;
    one worth eighty thousand is the reason the shop cannot pay its supplier.
    """
    tenant.require(Perm.REPORT_READ)
    rows = await AnalyticsService(db, tenant.actor).dead_stock(days=days, limit=limit)
    return {
        "days": days,
        "items": rows,
        "total_value": sum((row["stock_value"] for row in rows), Decimal("0")),
        "never_sold_count": len([row for row in rows if row["never_sold"]]),
    }


@router.get("/stock-ageing", summary="How long stock has been sitting")
async def stock_ageing(tenant: Tenant, db: DbSession) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    bands = await AnalyticsService(db, tenant.actor).stock_ageing()
    return {
        "bands": bands,
        "total_value": sum((band["value"] for band in bands), Decimal("0")),
    }


@router.get("/item-profit", summary="Profit per item")
async def item_profit(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Not the same list as sales per item: the best seller is often the thing
    the shop makes least on."""
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).item_profit(start, end, limit=limit)
    return {"start": start, "end": end, "items": rows}


@router.get("/party-profit", summary="Profit per customer")
async def party_profit(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).party_profit(start, end, limit=limit)
    return {"start": start, "end": end, "parties": rows}


@router.get("/discounts", summary="Margin given away as discount")
async def discounts(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Shopkeepers give discounts one bill at a time and never see the total."""
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    figures = await AnalyticsService(db, tenant.actor).discounts_given(start, end)
    return {"start": start, "end": end, **figures}


@router.get("/payment-modes", summary="How customers actually pay")
async def payment_modes(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).payment_modes(start, end)
    return {"start": start, "end": end, "modes": rows}


@router.get("/purchase-register", summary="Purchases in a period")
async def purchase_register(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).purchase_register(start, end)
    return {
        "start": start,
        "end": end,
        "rows": rows,
        "total": sum((row["total"] for row in rows), Decimal("0")),
    }


@router.get("/returns", summary="What came back")
async def returns(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    sales: bool = True,
) -> dict[str, Any]:
    """A customer who returns half of what they buy is a pattern nobody
    notices one credit note at a time."""
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).returns_register(start, end, sales=sales)
    return {
        "start": start,
        "end": end,
        "rows": rows,
        "total": sum((row["total"] for row in rows), Decimal("0")),
    }


@router.get("/expense-trend", summary="Spending against the period before")
async def expense_trend(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """A category on its own is a number; against last month it is a decision."""
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).expense_trend(start, end)
    return {"start": start, "end": end, "categories": rows}


@router.get("/by-user", summary="Sales by whoever raised them")
async def by_user(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).by_user(start, end)
    return {"start": start, "end": end, "users": rows}


@router.get("/stock-movement", summary="In, out and closing per item")
async def stock_movement(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    start, end = _window(start_date, end_date)
    rows = await AnalyticsService(db, tenant.actor).stock_movement(start, end, limit=limit)
    return {"start": start, "end": end, "items": rows}


@router.get("/balances", summary="Who owes what")
async def balances(
    tenant: Tenant, db: DbSession, receivable: bool = True
) -> dict[str, Any]:
    tenant.require(Perm.REPORT_READ)
    rows = await AnalyticsService(db, tenant.actor).customer_balances(receivable=receivable)
    return {
        "receivable": receivable,
        "parties": rows,
        "total": sum((row["balance"] for row in rows), Decimal("0")),
        "over_limit_count": len([row for row in rows if row["over_limit"]]),
    }


# Where each report's data actually comes from.
#
# A report either has a screen of its own already, or is a table a generic
# viewer can render from an endpoint. Keeping the mapping here rather than in
# the app means adding a report does not need an app release, and the app never
# has to guess a URL from a key.
_SCREENS = {
    "expiry": "expiry",
    "low-stock": "items?filter=low_stock",
    "cheques": "cheques",
    "loans": "loans",
    "accounts": "accounts",
    "godown-stock": "godowns",
    "price-lists": "pricing",
    "offers": "pricing",
    "loyalty": "loyalty",
    "recurring": "recurring",
    "production": "manufacturing",
    "fbr-return": "tax",
    "annexure-c": "tax",
    "batches": "expiry",
    "serials": "items",
    "item-ledger": "items",
    "party-statement": "parties",
}

_ENDPOINTS = {
    "dead-stock": "/reports/dead-stock",
    "stock-ageing": "/reports/stock-ageing",
    "item-profit": "/reports/item-profit",
    "party-profit": "/reports/party-profit",
    "discounts": "/reports/discounts",
    "payment-modes": "/reports/payment-modes",
    "purchase-register": "/reports/purchase-register",
    "returns": "/reports/returns",
    "expense-trend": "/reports/expense-trend",
    "by-user": "/reports/by-user",
    "stock-movement": "/reports/stock-movement",
    "balances": "/reports/balances",
    "profit-loss": "/reports/profit-loss",
    "balance-sheet": "/reports/balance-sheet",
    "cash-flow": "/reports/cash-flow",
    "daybook": "/reports/daybook",
    "sales": "/reports/sales",
    "top-items": "/reports/top-items",
    "top-parties": "/reports/top-parties",
    "ageing": "/reports/ageing",
    "tax": "/reports/tax",
}


def _decorate(catalogue: dict[str, Any]) -> dict[str, Any]:
    """Attach the route or endpoint each report is served by."""
    for group in catalogue["groups"]:
        for report in group["reports"]:
            report["screen"] = _SCREENS.get(report["key"])
            report["endpoint"] = _ENDPOINTS.get(report["key"])
    return catalogue


@router.get("/catalogue", summary="Every report this app can produce")
async def catalogue(tenant: Tenant) -> dict[str, Any]:
    """Listed so the reports screen is built from one place rather than from a
    hard-coded menu that drifts out of step with what exists.

    Each entry says where its own data comes from — either a screen the app
    already has, or an endpoint a generic viewer can render. The app therefore
    never has to guess, and a report added here appears without an app release.
    """
    tenant.require(Perm.REPORT_READ)
    return _decorate({
        "groups": [
            {
                "title": "Money",
                "reports": [
                    {"key": "profit-loss", "name": "Profit and loss",
                     "about": "What the shop earned and spent"},
                    {"key": "balance-sheet", "name": "Balance sheet",
                     "about": "What it owns and owes"},
                    {"key": "cash-flow", "name": "Cash flow",
                     "about": "Money in and out"},
                    {"key": "daybook", "name": "Day book",
                     "about": "Everything that happened, by day"},
                    {"key": "payment-modes", "name": "How customers pay",
                     "about": "Cash, bank, wallet — and how much of each"},
                    {"key": "discounts", "name": "Discounts given",
                     "about": "Margin that walked out the door"},
                ],
            },
            {
                "title": "Sales",
                "reports": [
                    {"key": "sales", "name": "Sales register",
                     "about": "Every bill in a period"},
                    {"key": "item-profit", "name": "Profit per item",
                     "about": "Which goods actually make money"},
                    {"key": "party-profit", "name": "Profit per customer",
                     "about": "Which customers are worth keeping"},
                    {"key": "top-items", "name": "Best sellers",
                     "about": "By quantity and by value"},
                    {"key": "top-parties", "name": "Biggest customers",
                     "about": "By what they spend"},
                    {"key": "returns", "name": "Returns",
                     "about": "What came back, and from whom"},
                    {"key": "by-user", "name": "Sales by staff",
                     "about": "Who raised what"},
                ],
            },
            {
                "title": "Stock",
                "reports": [
                    {"key": "stock-movement", "name": "Stock movement",
                     "about": "In, out and closing per item"},
                    {"key": "dead-stock", "name": "Dead stock",
                     "about": "Goods not selling, and what they tie up"},
                    {"key": "stock-ageing", "name": "Stock ageing",
                     "about": "How long it has been sitting"},
                    {"key": "expiry", "name": "Expiring stock",
                     "about": "Batches past or near their date"},
                    {"key": "low-stock", "name": "Low stock",
                     "about": "What to reorder"},
                ],
            },
            {
                "title": "Owed",
                "reports": [
                    {"key": "balances", "name": "Who owes you",
                     "about": "Outstanding, largest first"},
                    {"key": "ageing", "name": "Debt ageing",
                     "about": "How overdue each balance is"},
                    {"key": "party-statement", "name": "Customer statement",
                     "about": "One customer's whole account"},
                    {"key": "cheques", "name": "Cheques",
                     "about": "To deposit and to clear"},
                    {"key": "loans", "name": "Loans",
                     "about": "What is owed and the next instalment"},
                ],
            },
            {
                "title": "Where things are",
                "reports": [
                    {"key": "godown-stock", "name": "Stock by location",
                     "about": "What each godown or branch holds"},
                    {"key": "item-ledger", "name": "Item history",
                     "about": "Every movement of one item"},
                    {"key": "batches", "name": "Batches",
                     "about": "Lot numbers and their dates"},
                    {"key": "serials", "name": "Serial numbers",
                     "about": "Which units are in stock and which are sold"},
                    {"key": "accounts", "name": "Cash and bank book",
                     "about": "Balances and transfers between them"},
                ],
            },
            {
                "title": "Rates and offers",
                "reports": [
                    {"key": "price-lists", "name": "Price lists",
                     "about": "What each kind of customer pays"},
                    {"key": "offers", "name": "Offers taken",
                     "about": "Which discounts customers actually used"},
                    {"key": "loyalty", "name": "Points outstanding",
                     "about": "What customers are holding"},
                    {"key": "recurring", "name": "Repeating bills",
                     "about": "What is due and what has been raised"},
                ],
            },
            {
                "title": "Buying and making",
                "reports": [
                    {"key": "purchase-register", "name": "Purchase register",
                     "about": "Every supplier bill"},
                    {"key": "expense-trend", "name": "Expenses",
                     "about": "By category, against the period before"},
                    {"key": "production", "name": "What was made",
                     "about": "Runs and what each cost"},
                ],
            },
            {
                "title": "Tax",
                "reports": [
                    {"key": "tax", "name": "Tax summary",
                     "about": "Collected and paid"},
                    {"key": "fbr-return", "name": "Sales tax return",
                     "about": "The month's figures for the FBR"},
                    {"key": "annexure-c", "name": "Annexure C",
                     "about": "The sales register to upload"},
                ],
            },
        ]
    })
