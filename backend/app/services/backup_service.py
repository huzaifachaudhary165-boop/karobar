"""Export a whole shop to a file, and put it back.

Why this exists: the data lives on someone else's server. A shopkeeper who wants
to move hosts, keep their own copy, or simply not be locked in should be able to
walk away with everything in a format they can open.

The export is plain JSON — readable in any text editor, importable into a
spreadsheet — not a database dump. That is deliberate: a dump is only useful with
the same Postgres version and schema, which is exactly the lock-in this avoids.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError
from app.core.logging import log
from app.models.business import Business, BusinessSettings
from app.models.expense import Expense, ExpenseCategory
from app.models.item import Item, ItemCategory, Unit
from app.models.party import Party, PartyGroup
from app.models.payment import Account, Payment
from app.models.voucher import Voucher, VoucherLine
from app.services.base import ActorContext

FORMAT_VERSION = 1

# Ordered by dependency: a voucher references a party and an item, so those must
# already exist when it is restored. Restoring in list order is what makes the
# import a single pass with no second fix-up stage.
_TABLES: list[tuple[str, Any]] = [
    ("party_groups", PartyGroup),
    ("parties", Party),
    ("units", Unit),
    ("item_categories", ItemCategory),
    ("items", Item),
    ("accounts", Account),
    ("expense_categories", ExpenseCategory),
    ("expenses", Expense),
    ("vouchers", Voucher),
    ("voucher_lines", VoucherLine),
    ("payments", Payment),
]


def _plain(value: Any) -> Any:
    """JSON cannot hold a Decimal or a date, and float would quietly lose paise."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _revive(column: Any, value: Any) -> Any:
    """Turn an exported string back into what the column expects.

    Export flattens Decimal and date/datetime to strings so the file is readable
    and lossless. The database will not take them back in that form — SQLite is
    explicit about it ("Date type only accepts Python date objects"), and
    Postgres would coerce silently, which is worse. So the column's own type
    decides how to parse.
    """
    if value is None:
        return None

    # The app's portable column types (Money, TZDateTime, …) are TypeDecorators
    # wrapping a real type. Asking a decorator for `python_type` does not reliably
    # answer, so unwrap to the type the database actually sees.
    sql_type = column.type
    while hasattr(sql_type, "impl") and not isinstance(sql_type, type):
        sql_type = sql_type.impl if not isinstance(sql_type.impl, type) else sql_type.impl()

    if isinstance(sql_type, sa.Numeric) and isinstance(value, (str, int, float)):
        return Decimal(str(value))
    if isinstance(sql_type, sa.DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(sql_type, sa.Date) and isinstance(value, str):
        # A datetime string in a Date column loses its time part, deliberately.
        return date.fromisoformat(value[:10])
    return value


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: _plain(getattr(row, column.name))
        for column in row.__table__.columns
    }


class BackupService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def export(self) -> dict[str, Any]:
        """Everything belonging to this business, in one JSON object."""
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        settings_row = (
            await self.db.execute(
                select(BusinessSettings).where(
                    BusinessSettings.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "exported_at": datetime.utcnow().isoformat(),
            "business": _row_to_dict(business),
            "settings": _row_to_dict(settings_row) if settings_row else {},
            "data": {},
        }

        for name, model in _TABLES:
            rows = await self._rows_for(model)
            payload["data"][name] = [_row_to_dict(r) for r in rows]

        payload["counts"] = {name: len(rows) for name, rows in payload["data"].items()}
        log.info("backup.exported", business_id=self.business_id, counts=payload["counts"])
        return payload

    async def _rows_for(self, model: Any) -> list[Any]:
        # Voucher lines carry no business_id of their own; they are reached
        # through the voucher that owns them.
        if model is VoucherLine:
            stmt = (
                select(VoucherLine)
                .join(Voucher, VoucherLine.voucher_id == Voucher.id)
                .where(Voucher.business_id == self.business_id)
            )
        else:
            stmt = select(model).where(model.business_id == self.business_id)
        return list((await self.db.execute(stmt)).scalars().all())

    # ── restore ──────────────────────────────────────────────────
    async def restore(self, payload: dict[str, Any], *, replace: bool = False) -> dict[str, int]:
        """Load an export back into *this* business.

        Rows keep their original ids, so a restore is idempotent: importing the
        same file twice does not duplicate anything. Anything already present is
        skipped rather than overwritten — a restore should never destroy work
        done since the backup unless `replace` is explicitly asked for.
        """
        version = payload.get("format_version")
        if version != FORMAT_VERSION:
            raise BusinessRuleError(
                f"This backup is version {version}; this app reads version {FORMAT_VERSION}.",
                details={"found": version, "expected": FORMAT_VERSION},
            )

        data = payload.get("data")
        if not isinstance(data, dict):
            raise BusinessRuleError("That file does not look like a Karobar backup.")

        if replace:
            await self._wipe()

        restored: dict[str, int] = {}
        for name, model in _TABLES:
            rows = data.get(name) or []
            restored[name] = await self._insert_missing(model, rows)

        await self.db.flush()
        log.info("backup.restored", business_id=self.business_id, counts=restored)
        return restored

    async def _insert_missing(self, model: Any, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        existing = set(
            (await self.db.execute(select(model.id))).scalars().all()
        )
        columns = {c.name for c in model.__table__.columns}
        inserted = 0

        for row in rows:
            if not isinstance(row, dict) or row.get("id") in existing:
                continue

            values = {
                key: _revive(model.__table__.columns[key], value)
                for key, value in row.items()
                if key in columns
            }
            # Never trust a file to say which shop a row belongs to: that is how
            # a backup from one business would be restored into another.
            if "business_id" in columns:
                values["business_id"] = self.business_id

            self.db.add(model(**values))
            inserted += 1

        return inserted

    async def _wipe(self) -> None:
        """Delete this business's rows, children first."""
        for name, model in reversed(_TABLES):
            rows = await self._rows_for(model)
            for row in rows:
                await self.db.delete(row)
        await self.db.flush()
        log.warning("backup.wiped_before_restore", business_id=self.business_id)

    # ── file helpers ─────────────────────────────────────────────
    @staticmethod
    def to_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")

    @staticmethod
    def from_bytes(raw: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BusinessRuleError("That file is not readable JSON.") from exc
        if not isinstance(parsed, dict):
            raise BusinessRuleError("That file does not look like a Karobar backup.")
        return parsed
