"""Price lists and discount schemes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.money import ZERO, money
from app.core.pricing import (
    BASE_PRICES, ItemPrices, ListRule, Scheme, applies_on, best_scheme, enforce_floor,
    resolve_rate,
)
from app.models.base import utcnow
from app.models.item import Item
from app.models.party import Party
from app.models.pricing import DiscountScheme, PriceList, PriceListEntry
from app.services.base import BaseService, stamp_sync

SCOPES = ("bill", "item", "category", "party")


class PriceListService(BaseService[PriceList]):
    model = PriceList
    entity_name = "price_list"

    async def create(self, data: dict[str, Any]) -> PriceList:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        if client_uuid and (existing := await self.get_by_client_uuid(client_uuid)):
            return existing

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Give the price list a name.")
        if await self._name_taken(name):
            raise ConflictError(f"A price list called '{name}' already exists.")
        if (base := data.get("base_price", "sale")) not in BASE_PRICES:
            raise BusinessRuleError(f"'{base}' is not one of the prices an item carries.")

        data["name"] = name
        row = PriceList(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            **{k: v for k, v in data.items() if hasattr(PriceList, k)},
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        if row.is_default:
            await self._clear_default(row.id)
        await self.track("create", row, label=row.name)
        return row

    async def update(self, list_id: str, data: dict[str, Any]) -> PriceList:
        row = await self.get_or_404(list_id)
        if (name := data.get("name")) and name.strip().lower() != row.name.lower():
            if await self._name_taken(name):
                raise ConflictError(f"A price list called '{name}' already exists.")
            data["name"] = name.strip()

        changes = self.apply_fields(row, data)
        if row.is_default:
            await self._clear_default(row.id)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.name)
        return row

    async def delete(self, list_id: str) -> None:
        row = await self.get_or_404(list_id)
        using = (
            await self.db.execute(
                select(func.count()).select_from(Party).where(
                    Party.business_id == self.business_id,
                    Party.is_deleted.is_(False),
                    Party.price_list == row.id,
                )
            )
        ).scalar_one()
        if using:
            raise BusinessRuleError(
                f"{using} customer(s) are on '{row.name}'. Move them to another "
                "list before deleting it.",
                details={"party_count": int(using)},
            )
        await self.soft_delete(row, label=row.name)

    async def list_all(self) -> list[tuple[PriceList, int]]:
        counts = dict(
            (
                await self.db.execute(
                    select(PriceListEntry.price_list_id, func.count(PriceListEntry.id))
                    .where(PriceListEntry.business_id == self.business_id)
                    .group_by(PriceListEntry.price_list_id)
                )
            ).all()
        )
        rows = (
            await self.db.execute(
                self.base_query().order_by(PriceList.is_default.desc(), PriceList.name)
            )
        ).scalars().all()
        return [(row, int(counts.get(row.id, 0))) for row in rows]

    async def entries(self, list_id: str) -> list[tuple[PriceListEntry, Item]]:
        await self.get_or_404(list_id)
        rows = (
            await self.db.execute(
                select(PriceListEntry, Item)
                .join(Item, Item.id == PriceListEntry.item_id)
                .where(
                    PriceListEntry.business_id == self.business_id,
                    PriceListEntry.price_list_id == list_id,
                    Item.is_deleted.is_(False),
                )
                .order_by(Item.name)
            )
        ).all()
        return [(entry, item) for entry, item in rows]

    async def set_entry(
        self, list_id: str, item_id: str, price: Decimal, min_qty: Decimal | None = None
    ) -> PriceListEntry:
        await self.get_or_404(list_id)
        if price < 0:
            raise BusinessRuleError("A price cannot be negative.")

        row = (
            await self.db.execute(
                select(PriceListEntry).where(
                    PriceListEntry.business_id == self.business_id,
                    PriceListEntry.price_list_id == list_id,
                    PriceListEntry.item_id == item_id,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = PriceListEntry(
                business_id=self.business_id,
                price_list_id=list_id,
                item_id=item_id,
                price=money(price),
                min_qty=min_qty,
            )
            stamp_sync(row, self.actor)
            self.db.add(row)
            await self.db.flush()
        else:
            row.price = money(price)
            row.min_qty = min_qty
            row.bump_revision()

        await self.record_audit("update", row.id, entity_type="price_list_entry")
        return row

    async def remove_entry(self, list_id: str, item_id: str) -> None:
        row = (
            await self.db.execute(
                select(PriceListEntry).where(
                    PriceListEntry.business_id == self.business_id,
                    PriceListEntry.price_list_id == list_id,
                    PriceListEntry.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("That item is not on this list.")
        await self.db.delete(row)

    async def _clear_default(self, keep_id: str) -> None:
        for other in (
            await self.db.execute(
                self.base_query().where(
                    PriceList.id != keep_id, PriceList.is_default.is_(True)
                )
            )
        ).scalars().all():
            other.is_default = False
            other.bump_revision()

    async def _name_taken(self, name: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query()
                .where(func.lower(PriceList.name) == name.strip().lower())
                .limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None


class DiscountSchemeService(BaseService[DiscountScheme]):
    model = DiscountScheme
    entity_name = "discount_scheme"

    async def create(self, data: dict[str, Any]) -> DiscountScheme:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Give the offer a name — it goes on the bill.")
        if await self._name_taken(name):
            raise ConflictError(f"An offer called '{name}' already exists.")

        scope = data.get("scope", "bill")
        if scope not in SCOPES:
            raise BusinessRuleError(f"'{scope}' is not something a discount can apply to.")
        if scope == "item" and not data.get("item_id"):
            raise BusinessRuleError("Choose the item this offer is on.")
        if scope == "category" and not data.get("category_id"):
            raise BusinessRuleError("Choose the category this offer is on.")

        if (value := data.get("discount_value") or ZERO) <= 0:
            raise BusinessRuleError("An offer that takes nothing off is not an offer.")
        if data.get("discount_type", "percent") == "percent" and value > 100:
            raise BusinessRuleError("A percentage discount cannot be more than 100%.")

        starts, ends = data.get("starts_on"), data.get("ends_on")
        if starts and ends and ends < starts:
            raise BusinessRuleError("The offer would end before it starts.")

        data["name"] = name
        row = DiscountScheme(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            **{k: v for k, v in data.items() if hasattr(DiscountScheme, k)},
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def update(self, scheme_id: str, data: dict[str, Any]) -> DiscountScheme:
        row = await self.get_or_404(scheme_id)
        # Kept honest rather than editable: how often an offer ran is a record.
        data.pop("times_used", None)
        data.pop("last_used_at", None)

        starts = data.get("starts_on", row.starts_on)
        ends = data.get("ends_on", row.ends_on)
        if starts and ends and ends < starts:
            raise BusinessRuleError("The offer would end before it starts.")

        changes = self.apply_fields(row, data)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.name)
        return row

    async def delete(self, scheme_id: str) -> None:
        row = await self.get_or_404(scheme_id)
        await self.soft_delete(row, label=row.name)

    async def list_all(self, *, only_running: bool = False) -> list[DiscountScheme]:
        stmt = self.base_query()
        if only_running:
            today = date.today()
            stmt = stmt.where(
                DiscountScheme.is_active.is_(True),
                or_(DiscountScheme.starts_on.is_(None), DiscountScheme.starts_on <= today),
                or_(DiscountScheme.ends_on.is_(None), DiscountScheme.ends_on >= today),
            )
        return list(
            (
                await self.db.execute(
                    stmt.order_by(DiscountScheme.priority.desc(), DiscountScheme.name)
                )
            ).scalars().all()
        )

    async def _name_taken(self, name: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query()
                .where(func.lower(DiscountScheme.name) == name.strip().lower())
                .limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None


class QuoteService:
    """Works out what to put on a line before the shopkeeper agrees to it.

    Deliberately separate from creating the voucher. The bill screen asks for a
    rate, shows it, and sends back what was shown — repricing on save would mean
    the printed bill differs from the number the shopkeeper read out to the
    customer, which is the one thing a billing app must never do.
    """

    def __init__(self, db, actor) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def quote(
        self,
        item_ids: list[str],
        *,
        party_id: str | None = None,
        qty_by_item: dict[str, Decimal] | None = None,
        on_date: date | None = None,
    ) -> list[dict[str, Any]]:
        when = on_date or date.today()
        quantities = qty_by_item or {}

        items = (
            await self.db.execute(
                select(Item).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.id.in_(item_ids),
                )
            )
        ).scalars().all()
        found = {item.id: item for item in items}

        missing = [i for i in item_ids if i not in found]
        if missing:
            raise NotFoundError("Item not found.", details={"id": missing[0]})

        party, price_list = await self._party_and_list(party_id)
        entries = await self._entries_for(price_list, item_ids)
        schemes = await self._schemes_for(party, price_list, when)

        rule = (
            ListRule(price_list.adjust_percent, price_list.base_price)
            if price_list
            else None
        )

        out: list[dict[str, Any]] = []
        for item_id in item_ids:
            item = found[item_id]
            qty = quantities.get(item_id, Decimal("1"))
            entry = entries.get(item_id)

            # A tiered rate only applies once enough is being bought.
            entry_price = None
            if entry is not None and (entry.min_qty is None or qty >= entry.min_qty):
                entry_price = entry.price

            line = resolve_rate(_prices_of(item), entry_price=entry_price, rule=rule)
            rate, held = enforce_floor(line.rate, item.min_sale_price)

            line_total = money(rate * qty)
            applicable = [s for s in schemes if _scheme_covers(s, item)]
            chosen = best_scheme(
                [_as_scheme(s) for s in applicable], line_total=line_total, qty=qty
            )

            # A party's own standing discount is the fallback when no offer
            # fires — it is what was agreed with them, not a promotion.
            discount = chosen[1] if chosen else ZERO
            scheme_name = chosen[0].name if chosen else None
            if not chosen and party and party.default_discount_percent:
                discount = money(line_total * party.default_discount_percent / 100)
                scheme_name = "Agreed discount"

            out.append(
                {
                    "item_id": item_id,
                    "rate": rate,
                    "source": line.source,
                    "held_at_minimum": held,
                    "qty": qty,
                    "line_total": line_total,
                    "discount": discount,
                    "net": money(line_total - discount),
                    "scheme_name": scheme_name,
                    "price_list_id": price_list.id if price_list else None,
                    "price_list_name": price_list.name if price_list else None,
                }
            )
        return out

    async def mark_used(self, scheme_names: list[str]) -> None:
        """Records that an offer was actually taken, for the offers report."""
        if not scheme_names:
            return
        rows = (
            await self.db.execute(
                select(DiscountScheme).where(
                    DiscountScheme.business_id == self.business_id,
                    DiscountScheme.name.in_(scheme_names),
                )
            )
        ).scalars().all()
        for row in rows:
            row.times_used += 1
            row.last_used_at = utcnow()

    async def _party_and_list(
        self, party_id: str | None
    ) -> tuple[Party | None, PriceList | None]:
        party = None
        if party_id:
            party = (
                await self.db.execute(
                    select(Party).where(
                        Party.id == party_id,
                        Party.business_id == self.business_id,
                        Party.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()

        stmt = select(PriceList).where(
            PriceList.business_id == self.business_id,
            PriceList.is_deleted.is_(False),
            PriceList.is_active.is_(True),
        )
        if party and party.price_list:
            chosen = (
                await self.db.execute(stmt.where(PriceList.id == party.price_list))
            ).scalar_one_or_none()
            if chosen:
                return party, chosen

        # No list of their own: the shop's default, if it has one.
        return party, (
            await self.db.execute(stmt.where(PriceList.is_default.is_(True)).limit(1))
        ).scalar_one_or_none()

    async def _entries_for(
        self, price_list: PriceList | None, item_ids: list[str]
    ) -> dict[str, PriceListEntry]:
        if price_list is None:
            return {}
        rows = (
            await self.db.execute(
                select(PriceListEntry).where(
                    PriceListEntry.business_id == self.business_id,
                    PriceListEntry.price_list_id == price_list.id,
                    PriceListEntry.item_id.in_(item_ids),
                )
            )
        ).scalars().all()
        return {row.item_id: row for row in rows}

    async def _schemes_for(
        self, party: Party | None, price_list: PriceList | None, when: date
    ) -> list[DiscountScheme]:
        rows = (
            await self.db.execute(
                select(DiscountScheme).where(
                    DiscountScheme.business_id == self.business_id,
                    DiscountScheme.is_deleted.is_(False),
                    DiscountScheme.is_active.is_(True),
                )
            )
        ).scalars().all()

        out = []
        for scheme in rows:
            if not applies_on(scheme.starts_on, scheme.ends_on, when, scheme.is_active):
                continue
            # An offer aimed at one customer or one list must not reach others.
            if scheme.party_id and (party is None or scheme.party_id != party.id):
                continue
            if scheme.price_list_id and (
                price_list is None or scheme.price_list_id != price_list.id
            ):
                continue
            out.append(scheme)
        return out


def _prices_of(item: Item) -> ItemPrices:
    return ItemPrices(
        sale=item.sale_price,
        purchase=item.purchase_price,
        mrp=item.mrp,
        wholesale=item.wholesale_price,
        min_sale=item.min_sale_price,
    )


def _as_scheme(row: DiscountScheme) -> Scheme:
    return Scheme(
        name=row.name,
        discount_type=row.discount_type,
        discount_value=row.discount_value,
        max_discount=row.max_discount,
        min_amount=row.min_amount,
        min_qty=row.min_qty,
        priority=row.priority,
        scope=row.scope,
    )


def _scheme_covers(scheme: DiscountScheme, item: Item) -> bool:
    if scheme.scope == "item":
        return scheme.item_id == item.id
    if scheme.scope == "category":
        return scheme.category_id is not None and scheme.category_id == item.category_id
    return True
