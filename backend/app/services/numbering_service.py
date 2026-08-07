"""Document numbering — gap-free, concurrency-safe, per-series and per-period."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.business import BusinessSettings
from app.models.enums import VoucherType
from app.models.system import NumberSequence
from app.utils.dates import financial_year_bounds

SERIES_PREFIX_FIELD: dict[str, str] = {
    VoucherType.SALE: "invoice_prefix",
    VoucherType.PURCHASE: "purchase_prefix",
    VoucherType.QUOTATION: "quotation_prefix",
    # PROFORMA deliberately absent, so it keeps its own PRO- prefix. Sharing the
    # quotation's produced a quotation and a proforma both numbered QTN-0001:
    # the unique index tolerates it because it is scoped by type, but a customer
    # holding both pieces of paper cannot tell which is which.
    "payment_in": "payment_prefix",
    # `payment_out` is deliberately absent. Money received and money paid are
    # counted in separate series, so sharing a prefix would give the first
    # receipt and the first payment the same number — and a shop that takes one
    # payment and then makes one would be refused on the second.
}

FALLBACK_PREFIX: dict[str, str] = {
    VoucherType.SALE: "INV-",
    VoucherType.PURCHASE: "PUR-",
    VoucherType.SALE_RETURN: "CRN-",
    VoucherType.PURCHASE_RETURN: "DBN-",
    VoucherType.QUOTATION: "QTN-",
    VoucherType.PROFORMA: "PRO-",
    VoucherType.DELIVERY_CHALLAN: "DC-",
    VoucherType.SALE_ORDER: "SO-",
    VoucherType.PURCHASE_ORDER: "PO-",
    "payment_in": "RCP-",
    "payment_out": "PMT-",
    "expense": "EXP-",
    "production": "MFG-",
}


class NumberingService:
    def __init__(self, db: AsyncSession, business_id: str) -> None:
        self.db = db
        self.business_id = business_id

    async def next_number(
        self,
        series_key: str,
        *,
        settings_row: BusinessSettings | None = None,
        on_date: date | None = None,
    ) -> tuple[str, int]:
        """Returns (formatted_number, sequence). Locks the counter row so two
        concurrent invoices can never take the same number."""
        cfg = settings_row or await self._settings()
        period = self._period(cfg, on_date or date.today())
        prefix = self._prefix(series_key, cfg)
        padding = (cfg.number_padding if cfg else 4) or 4

        seq_row = await self._locked_sequence(series_key, period, prefix, padding)
        seq_row.last_number += 1
        seq_row.prefix = prefix
        seq_row.padding = padding
        return self._format(prefix, seq_row.last_number, padding, period), seq_row.last_number

    async def peek_number(self, series_key: str, on_date: date | None = None) -> str:
        """Preview the next number without consuming it (used by the new-invoice screen)."""
        cfg = await self._settings()
        period = self._period(cfg, on_date or date.today())
        prefix = self._prefix(series_key, cfg)
        padding = (cfg.number_padding if cfg else 4) or 4
        row = (
            await self.db.execute(
                select(NumberSequence).where(
                    NumberSequence.business_id == self.business_id,
                    NumberSequence.series_key == series_key,
                    NumberSequence.period == period,
                )
            )
        ).scalar_one_or_none()
        return self._format(prefix, (row.last_number if row else 0) + 1, padding, period)

    async def reserve_explicit(self, series_key: str, number: str, on_date: date | None = None) -> None:
        """When a user types their own number, push the counter past it so the
        next auto-number doesn't collide."""
        digits = "".join(ch for ch in number if ch.isdigit())
        if not digits:
            return
        try:
            value = int(digits[-9:])
        except ValueError:
            return
        cfg = await self._settings()
        period = self._period(cfg, on_date or date.today())
        row = await self._locked_sequence(
            series_key, period, self._prefix(series_key, cfg), (cfg.number_padding if cfg else 4) or 4
        )
        row.last_number = max(row.last_number, value)

    # ── internals ────────────────────────────────────────────────
    async def _settings(self) -> BusinessSettings | None:
        return (
            await self.db.execute(
                select(BusinessSettings).where(BusinessSettings.business_id == self.business_id)
            )
        ).scalar_one_or_none()

    def _period(self, cfg: BusinessSettings | None, on_date: date) -> str:
        if not cfg or not cfg.reset_numbering_yearly:
            return "all"
        start, _ = financial_year_bounds(on_date, 7)
        return f"{start.year}-{str((start.year + 1) % 100).zfill(2)}"

    def _prefix(self, series_key: str, cfg: BusinessSettings | None) -> str:
        field = SERIES_PREFIX_FIELD.get(series_key)
        if cfg and field and getattr(cfg, field, None):
            return getattr(cfg, field)
        return FALLBACK_PREFIX.get(series_key, f"{series_key[:3].upper()}-")

    def _format(self, prefix: str, number: int, padding: int, period: str) -> str:
        body = str(number).zfill(max(1, padding))
        if period != "all":
            return f"{prefix}{period}/{body}"
        return f"{prefix}{body}"

    async def _locked_sequence(
        self, series_key: str, period: str, prefix: str, padding: int
    ) -> NumberSequence:
        stmt = select(NumberSequence).where(
            NumberSequence.business_id == self.business_id,
            NumberSequence.series_key == series_key,
            NumberSequence.period == period,
        )
        # SQLite has no row locks (single writer anyway); Postgres needs FOR UPDATE.
        if not settings.is_sqlite:
            stmt = stmt.with_for_update()

        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = NumberSequence(
                business_id=self.business_id,
                series_key=series_key,
                period=period,
                prefix=prefix,
                padding=padding,
                last_number=0,
            )
            self.db.add(row)
            await self.db.flush()
        return row
