"""AI business insights: gather real figures, then have the model narrate them.

Numbers come from the report service — the model only interprets, never computes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ai_client
from app.ai.prompts import INSIGHT_SYSTEM
from app.core.config import settings
from app.core.errors import AIError
from app.core.logging import log
from app.core.money import ZERO, D, format_money, growth_pct, money
from app.models.ai import AiInsight
from app.services.base import ActorContext
from app.services.item_service import ItemService
from app.services.party_service import PartyService
from app.services.report_service import ReportService
from app.utils.dates import previous_period, resolve_period

INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["trend", "anomaly", "suggestion", "alert", "win"],
                    },
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                    "title": {"type": "string", "maxLength": 90},
                    "body": {
                        "type": "string",
                        "maxLength": 320,
                        "description": "Two sentences max. Must cite the figures it rests on.",
                    },
                    "metric_used": {
                        "type": "string",
                        "description": "Which figure from the data this is based on.",
                    },
                    "action": {
                        "type": ["string", "null"],
                        "description": "One concrete next step, or null.",
                    },
                },
                "required": ["kind", "severity", "title", "body", "metric_used"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}


class InsightService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""
        self.reports = ReportService(db, actor)
        self.items = ItemService(db, actor)
        self.parties = PartyService(db, actor)

    async def generate(self, period: str = "this_month", *, refresh: bool = False) -> list[AiInsight]:
        start, end = resolve_period(period)

        if not refresh:
            existing = await self._cached(start, end)
            if existing:
                return existing

        facts = await self.collect(period)
        rows = await self._narrate(facts, start, end)

        if not rows:
            rows = self._rule_based(facts, start, end)

        for row in rows:
            self.db.add(row)
        await self.db.flush()
        return rows

    # ── facts ────────────────────────────────────────────────────
    async def collect(self, period: str) -> dict[str, Any]:
        """Everything the model is allowed to reason over. No estimates here."""
        start, end = resolve_period(period)
        prev_start, prev_end = previous_period(start, end)

        dashboard = await self.reports.dashboard(period)
        pl = await self.reports.profit_and_loss(start, end)
        top_now = await self.reports.top_items(start, end, limit=8)
        top_before = {r["name"]: r for r in await self.reports.top_items(prev_start, prev_end, 20)}
        ageing = await self.parties.ageing(receivable=True)
        low_stock = await self.items.low_stock_items(limit=10)
        expenses = await self.reports._expense_breakdown(start, end)  # noqa: SLF001 — same package

        item_rows = []
        for row in top_now:
            before = top_before.get(row["name"])
            item_rows.append(
                {
                    "name": row["name"],
                    "revenue": self._m(row["revenue"]),
                    "profit": self._m(row["profit"]),
                    "margin_percent": _pct(row["profit"], row["revenue"]),
                    "qty_sold": str(row["quantity"]),
                    "revenue_change_percent": (
                        str(growth_pct(row["revenue"], before["revenue"])) if before else None
                    ),
                }
            )

        return {
            "period": {"from": start.isoformat(), "to": end.isoformat(), "label": period},
            "previous_period": {"from": prev_start.isoformat(), "to": prev_end.isoformat()},
            "totals": {
                "sales": self._m(dashboard["sales"]["value"]),
                "sales_change_percent": _opt(dashboard["sales"]["change_percent"]),
                "purchases": self._m(dashboard["purchases"]["value"]),
                "expenses": self._m(dashboard["expenses"]["value"]),
                "expenses_change_percent": _opt(dashboard["expenses"]["change_percent"]),
                "gross_profit": self._m(pl["gross_profit"]),
                "gross_margin_percent": str(pl["gross_margin_percent"]),
                "net_profit": self._m(pl["net_profit"]),
                "net_margin_percent": str(pl["net_margin_percent"]),
                "money_collected": self._m(dashboard["collections"]["value"]),
                "invoice_count": dashboard["invoice_count"],
            },
            "position": {
                "receivable": self._m(dashboard["receivable"]),
                "payable": self._m(dashboard["payable"]),
                "cash_in_hand": self._m(dashboard["cash_in_hand"]),
                "bank_balance": self._m(dashboard["bank_balance"]),
                "stock_value": self._m(dashboard["stock_value"]),
                "overdue_amount": self._m(dashboard["overdue_amount"]),
                "overdue_invoice_count": dashboard["overdue_invoice_count"],
            },
            "top_items": item_rows,
            "expense_breakdown": [
                {"category": e["category"], "amount": self._m(e["amount"]), "count": e["count"]}
                for e in expenses[:8]
            ],
            "receivable_ageing": [
                {"bucket": b["label"], "amount": self._m(b["amount"]), "invoices": b["count"]}
                for b in ageing["buckets"]
            ],
            "slowest_payers": [
                {
                    "name": p["party_name"],
                    "outstanding": self._m(p["total"]),
                    "oldest_due": p["oldest_due_date"].isoformat(),
                }
                for p in ageing["parties"][:5]
            ],
            "low_stock": [
                {"name": i.name, "stock": str(i.stock_qty), "reorder_at": str(i.low_stock_qty)}
                for i in low_stock
            ],
            "top_customers": [
                {"name": c["name"], "sales": self._m(c["total"]), "outstanding": self._m(c["outstanding"])}
                for c in dashboard["top_parties"][:5]
            ],
        }

    # ── narration ────────────────────────────────────────────────
    async def _narrate(self, facts: dict[str, Any], start: date, end: date) -> list[AiInsight]:
        if not ai_client.available:
            return []
        import json  # noqa: PLC0415

        try:
            result = await ai_client.complete(
                [
                    {
                        "role": "user",
                        "content": (
                            "Here is this shop's data for the period. Produce the most useful "
                            "observations a busy owner would act on today.\n\n"
                            + json.dumps(facts, ensure_ascii=False, indent=1)
                        ),
                    }
                ],
                system=INSIGHT_SYSTEM,
                output_schema=INSIGHT_SCHEMA,
                max_tokens=3000,
                effort="high",
            )
            if result.is_refusal or not result.text:
                return []
            payload = json.loads(result.text)
        except (AIError, json.JSONDecodeError) as exc:
            log.warning("insights.generation_failed", error=str(exc)[:300])
            return []

        return [
            AiInsight(
                business_id=self.business_id,
                kind=row["kind"],
                severity=row["severity"],
                title=row["title"],
                body=row["body"],
                metrics={"basis": row.get("metric_used")},
                action={"text": row["action"]} if row.get("action") else None,
                period_start=start.isoformat(),
                period_end=end.isoformat(),
            )
            for row in payload.get("insights", [])
        ]

    # ── deterministic fallback ───────────────────────────────────
    def _rule_based(self, facts: dict[str, Any], start: date, end: date) -> list[AiInsight]:
        """Runs when AI is off or unavailable, so the dashboard is never empty."""
        rows: list[AiInsight] = []

        def add(kind: str, severity: str, title: str, body: str) -> None:
            rows.append(
                AiInsight(
                    business_id=self.business_id, kind=kind, severity=severity,
                    title=title, body=body,
                    period_start=start.isoformat(), period_end=end.isoformat(),
                )
            )

        position = facts["position"]
        totals = facts["totals"]

        if int(position["overdue_invoice_count"]) > 0:
            add(
                "alert", "warning",
                f"{position['overdue_invoice_count']} overdue invoice(s)",
                f"{position['overdue_amount']} is past its due date. "
                f"Oldest first: {', '.join(p['name'] for p in facts['slowest_payers'][:3]) or '—'}.",
            )
        if facts["low_stock"]:
            names = ", ".join(i["name"] for i in facts["low_stock"][:3])
            add(
                "alert", "info",
                f"{len(facts['low_stock'])} item(s) running low",
                f"Reorder soon: {names}.",
            )
        change = totals.get("sales_change_percent")
        if change is not None and D(change) < -15:
            add(
                "trend", "warning", "Sales are down on the previous period",
                f"Sales of {totals['sales']} are {change}% below the previous period.",
            )
        elif change is not None and D(change) > 15:
            add(
                "win", "info", "Sales are up on the previous period",
                f"Sales of {totals['sales']} are {change}% above the previous period.",
            )
        if D(totals["net_margin_percent"]) < 5 and D(totals["sales"].replace(",", "")[2:] or 0) > 0:
            add(
                "suggestion", "warning", "Thin net margin",
                f"Net margin is {totals['net_margin_percent']}% after "
                f"{totals['expenses']} of expenses. Check pricing on your top sellers.",
            )
        return rows

    # ── storage ──────────────────────────────────────────────────
    async def _cached(self, start: date, end: date) -> list[AiInsight]:
        rows = await self.db.execute(
            select(AiInsight)
            .where(
                AiInsight.business_id == self.business_id,
                AiInsight.period_start == start.isoformat(),
                AiInsight.period_end == end.isoformat(),
                AiInsight.is_dismissed.is_(False),
            )
            .order_by(AiInsight.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_recent(self, limit: int = 20) -> list[AiInsight]:
        rows = await self.db.execute(
            select(AiInsight)
            .where(AiInsight.business_id == self.business_id, AiInsight.is_dismissed.is_(False))
            .order_by(AiInsight.created_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def dismiss(self, insight_id: str) -> None:
        row = (
            await self.db.execute(
                select(AiInsight).where(
                    AiInsight.id == insight_id, AiInsight.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        if row:
            row.is_dismissed = True

    def _m(self, value: Any) -> str:
        return format_money(value or ZERO, symbol="")


def _pct(part: Any, whole: Any) -> str:
    w = D(whole)
    return "0" if w == ZERO else str(money(D(part) / w * 100))


def _opt(value: Any) -> str | None:
    return None if value is None else str(value)
