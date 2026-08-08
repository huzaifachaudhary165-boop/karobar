"""The invoice engine: line maths, tax split, stock movements and party ledger.

Rules that hold for every document:
  * money is stored, never recomputed on read;
  * stock and party balance are only touched through StockService / PartyService;
  * editing a posted document reverses its side effects before re-applying them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.money import ZERO, D, money, pct, qty, rupee
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.business import Business, BusinessSettings
from app.models.enums import (
    CONVERTIBLE_TO, DiscountType, PaymentDirection, StockMovement, VoucherStatus, VoucherType,
)
from app.models.item import Item
from app.models.party import Party
from app.models.voucher import Voucher, VoucherLine
from app.schemas.voucher import VoucherCreate, VoucherLineInput, VoucherUpdate
from app.services.base import ActorContext, BaseService, stamp_sync
from app.services.item_service import ItemService, SerialService, StockService
from app.services.numbering_service import NumberingService
from app.services.party_service import PartyService
from app.utils.tax import compute_line_tax, is_interstate

# Documents whose totals should never change after they are settled.
_LOCKED_STATUSES = {VoucherStatus.CANCELLED, VoucherStatus.CONVERTED}


def _has_strn(party: Party | None) -> bool:
    """Whether a buyer is registered for sales tax.

    The STRN, not the NTN: an NTN is income tax registration and does not
    exempt a buyer from further tax. Treating the two as the same is how a
    shop ends up under-charging.
    """
    return bool(party and party.strn and party.strn.strip())


def _label(voucher_type: str) -> str:
    """'purchase_order' → 'purchase order', for a message a shopkeeper reads."""
    return str(voucher_type).replace("_", " ")


class VoucherService(BaseService[Voucher]):
    model = Voucher
    entity_name = "voucher"

    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        super().__init__(db, actor)
        self.parties = PartyService(db, actor)
        self.items = ItemService(db, actor)
        self.stock = StockService(db, actor)
        self.serials = SerialService(db, actor)
        self.numbering = NumberingService(db, self.business_id)
        self._settings: BusinessSettings | None = None
        self._business: Business | None = None

    # ── create ───────────────────────────────────────────────────
    async def create(self, payload: VoucherCreate) -> Voucher:
        if payload.client_uuid:
            existing = await self.get_by_client_uuid(payload.client_uuid)
            if existing:
                return existing

        cfg = await self.settings()
        biz = await self.business()
        vtype = VoucherType(payload.voucher_type)
        vdate = payload.voucher_date or date.today()

        party = await self._resolve_party(payload, vtype)
        interstate = self._is_interstate(biz, party, payload.place_of_supply)
        inclusive = payload.is_tax_inclusive if payload.is_tax_inclusive is not None else cfg.prices_include_tax

        if payload.number:
            await self._assert_number_free(vtype, payload.number)
            number = payload.number
            sequence = 0
            await self.numbering.reserve_explicit(str(vtype), number, vdate)
        else:
            number, sequence = await self.numbering.next_number(str(vtype), settings_row=cfg, on_date=vdate)

        voucher = Voucher(
            business_id=self.business_id,
            voucher_type=str(vtype),
            number=number,
            sequence=sequence,
            voucher_date=vdate,
            due_date=payload.due_date or self._default_due_date(vdate, party, cfg, vtype),
            reference_number=payload.reference_number,
            party_id=party.id if party else None,
            party_name=(party.name if party else payload.party_name),
            party_phone=(party.phone if party else payload.party_phone),
            party_gstin=(party.gstin or party.ntn) if party else None,
            billing_address=payload.billing_address or (party.billing_address if party else None),
            shipping_address=payload.shipping_address or (party.shipping_address if party else None),
            place_of_supply=payload.place_of_supply or (party.state_code if party else biz.state_code),
            discount_type=str(payload.discount_type),
            discount_value=money(payload.discount_value),
            shipping_charge=money(payload.shipping_charge),
            packaging_charge=money(payload.packaging_charge),
            other_charge=money(payload.other_charge),
            is_tax_inclusive=inclusive,
            is_interstate=interstate,
            notes=payload.notes,
            terms=payload.terms or cfg.terms_and_conditions,
            transport_details=payload.transport_details or {},
            custom_fields=payload.custom_fields or {},
            parent_voucher_id=payload.parent_voucher_id,
            source=payload.source,
            status=str(payload.status) if payload.status else VoucherStatus.UNPAID,
            created_by=self.actor.user_id,
        )
        stamp_sync(voucher, self.actor, client_uuid=payload.client_uuid)
        self.db.add(voucher)
        await self.db.flush()

        await self._build_lines(voucher, payload.lines, interstate=interstate, inclusive=inclusive)
        # A walk-in with no party at all is unregistered by definition, which
        # is precisely the case further tax exists for.
        self._compute_totals(
            voucher, cfg, buyer_registered=_has_strn(party)
        )

        is_draft = voucher.status == VoucherStatus.DRAFT
        if not is_draft:
            await self._apply_stock(voucher, vtype)
            await self._apply_ledger(voucher, vtype, party)

        voucher.status = voucher.compute_status()
        await self.db.flush()

        if payload.payment and not is_draft and vtype.affects_ledger:
            await self._record_inline_payment(voucher, payload.payment, party)

        # Points are given here rather than by the caller, so a sale raised by
        # the AI, by a recurring schedule or by an import earns them just the
        # same as one keyed at the counter. A loyalty scheme a customer only
        # gets credit for some of the time is worse than none.
        if not is_draft and vtype == VoucherType.SALE and party is not None:
            from app.services.loyalty_service import LoyaltyService  # avoids a cycle

            await LoyaltyService(self.db, self.actor).earn(
                party.id, voucher.total,
                voucher_id=voucher.id, voucher_number=voucher.number, on=vdate,
            )

        await self.track("create", voucher, label=f"{voucher.voucher_type} {voucher.number}")
        self.log("voucher.created", voucher_id=voucher.id, number=voucher.number, total=str(voucher.total))
        return voucher

    # ── update ───────────────────────────────────────────────────
    async def update(self, voucher_id: str, payload: VoucherUpdate) -> Voucher:
        voucher = await self.get_or_404(voucher_id)
        if voucher.status in _LOCKED_STATUSES:
            raise BusinessRuleError(
                f"A {voucher.status} document cannot be edited.",
                details={"status": voucher.status},
            )

        cfg = await self.settings()
        biz = await self.business()
        vtype = voucher.type_enum
        data = payload.model_dump(exclude_unset=True)

        was_posted = voucher.status != VoucherStatus.DRAFT
        if was_posted:
            await self._reverse_stock(voucher)
            await self._reverse_ledger(voucher)

        old_snapshot = {
            "total": str(voucher.total),
            "line_count": len(voucher.lines),
            "party_id": voucher.party_id,
        }

        if "party_id" in data and data["party_id"] != voucher.party_id:
            new_party = await self.parties.get_or_404(data["party_id"]) if data["party_id"] else None
            voucher.party_id = new_party.id if new_party else None
            voucher.party_name = new_party.name if new_party else data.get("party_name")
            voucher.party_phone = new_party.phone if new_party else None
            voucher.party_gstin = (new_party.gstin or new_party.ntn) if new_party else None
            voucher.is_interstate = self._is_interstate(biz, new_party, voucher.place_of_supply)

        for field in (
            "voucher_date", "due_date", "reference_number", "party_name", "party_phone",
            "billing_address", "shipping_address", "place_of_supply", "notes", "terms",
            "transport_details", "custom_fields", "shipping_charge", "packaging_charge",
            "other_charge", "discount_type", "discount_value", "is_tax_inclusive",
        ):
            if field in data and data[field] is not None:
                setattr(voucher, field, data[field])

        if data.get("lines") is not None:
            for line in list(voucher.lines):
                await self.db.delete(line)
            voucher.lines.clear()
            await self.db.flush()
            await self._build_lines(
                voucher,
                [VoucherLineInput.model_validate(x) if isinstance(x, dict) else x for x in data["lines"]],
                interstate=voucher.is_interstate,
                inclusive=voucher.is_tax_inclusive,
            )

        if "status" in data and data["status"]:
            voucher.status = str(data["status"])

        party = (
            await self.parties.get(voucher.party_id) if voucher.party_id else None
        )
        self._compute_totals(voucher, cfg, buyer_registered=_has_strn(party))

        if voucher.status != VoucherStatus.DRAFT:
            party = await self.parties.get(voucher.party_id) if voucher.party_id else None
            await self._apply_stock(voucher, vtype)
            await self._apply_ledger(voucher, vtype, party)

        voucher.status = voucher.compute_status()
        voucher.updated_by = self.actor.user_id
        voucher.bump_revision()
        await self.db.flush()

        await self.track(
            "update", voucher,
            changes={"before": old_snapshot, "after": {"total": str(voucher.total), "line_count": len(voucher.lines)}},
            label=f"{voucher.voucher_type} {voucher.number}",
        )
        return voucher

    # ── cancel / delete ──────────────────────────────────────────
    async def cancel(self, voucher_id: str, reason: str | None = None) -> Voucher:
        voucher = await self.get_or_404(voucher_id)
        if voucher.status == VoucherStatus.CANCELLED:
            return voucher

        from app.services.loyalty_service import LoyaltyService  # avoids a cycle

        loyalty = LoyaltyService(self.db, self.actor)

        # Before the check below, not after: points the shop itself put on the
        # bill are not a payment the shopkeeper has to make a decision about,
        # and refusing to cancel until they "delete the payment" asks them to
        # go looking for something they never made.
        # Clearing an allocation writes paid_amount straight onto this same
        # voucher object, so the check below already sees the new figure.
        await loyalty.release_tender(voucher.id)

        if voucher.paid_amount > 0:
            raise BusinessRuleError(
                "This invoice has payments against it. Delete or reallocate the payments first.",
                details={"paid_amount": str(voucher.paid_amount)},
            )
        await self._reverse_stock(voucher)
        await self._reverse_ledger(voucher)

        # A cancelled bill that leaves the customer's points as they were is a
        # bill that gave something away for nothing.
        await loyalty.reverse(voucher.id)

        voucher.status = VoucherStatus.CANCELLED
        voucher.balance_amount = ZERO
        voucher.notes = f"{voucher.notes or ''}\n[Cancelled] {reason or ''}".strip()
        voucher.bump_revision()
        await self.track("cancel", voucher, label=voucher.number, changes={"reason": reason})
        return voucher

    async def delete(self, voucher_id: str) -> None:
        voucher = await self.get_or_404(voucher_id)
        if voucher.paid_amount > 0:
            raise BusinessRuleError(
                "Remove the payments linked to this invoice before deleting it.",
                details={"paid_amount": str(voucher.paid_amount)},
            )
        if voucher.status != VoucherStatus.CANCELLED:
            await self._reverse_stock(voucher)
            await self._reverse_ledger(voucher)
        await self.soft_delete(voucher, label=f"{voucher.voucher_type} {voucher.number}")

    # ── conversion & returns ─────────────────────────────────────
    async def convert(
        self, voucher_id: str, target_type: VoucherType, *, voucher_date: date | None = None
    ) -> Voucher:
        """Quotation → invoice, order → invoice, challan → invoice."""
        source = await self.get_or_404(voucher_id)
        if source.status == VoucherStatus.CONVERTED:
            raise ConflictError("This document has already been converted.")
        if source.status == VoucherStatus.CANCELLED:
            raise BusinessRuleError("A cancelled document cannot be converted.")

        allowed = CONVERTIBLE_TO.get(VoucherType(source.voucher_type), frozenset())
        if VoucherType(target_type) not in allowed:
            raise BusinessRuleError(
                f"A {_label(source.voucher_type)} cannot become a "
                f"{_label(target_type)}."
                + (
                    f" It can become: {', '.join(sorted(_label(t) for t in allowed))}."
                    if allowed
                    else ""
                ),
                code="invalid_conversion",
                details={"from": source.voucher_type, "allowed": sorted(allowed)},
            )

        payload = VoucherCreate(
            voucher_type=target_type,
            voucher_date=voucher_date or date.today(),
            party_id=source.party_id,
            party_name=source.party_name,
            party_phone=source.party_phone,
            billing_address=source.billing_address,
            shipping_address=source.shipping_address,
            place_of_supply=source.place_of_supply,
            discount_type=DiscountType(source.discount_type),
            discount_value=source.discount_value,
            shipping_charge=source.shipping_charge,
            packaging_charge=source.packaging_charge,
            other_charge=source.other_charge,
            is_tax_inclusive=source.is_tax_inclusive,
            notes=source.notes,
            terms=source.terms,
            parent_voucher_id=source.id,
            lines=[
                VoucherLineInput(
                    item_id=line.item_id,
                    item_name=line.item_name,
                    description=line.description,
                    hsn_code=line.hsn_code,
                    unit_label=line.unit_label,
                    qty=line.qty,
                    free_qty=line.free_qty,
                    rate=line.rate,
                    mrp=line.mrp,
                    cost_price=line.cost_price,
                    discount_type=DiscountType(line.discount_type),
                    discount_value=line.discount_value,
                    tax_rate=line.tax_rate,
                    cess_rate=line.cess_rate,
                    batch_id=line.batch_id,
                )
                for line in source.lines
            ],
        )
        created = await self.create(payload)
        source.status = VoucherStatus.CONVERTED
        source.converted_to_id = created.id
        source.bump_revision()
        await self.track("convert", source, label=source.number, changes={"to": created.id})
        return created

    async def create_return(
        self,
        voucher_id: str,
        *,
        lines: list[dict[str, Any]] | None = None,
        return_date: date | None = None,
        reason: str | None = None,
    ) -> Voucher:
        """Credit note against a sale, or debit note against a purchase."""
        original = await self.get_or_404(voucher_id)
        vtype = original.type_enum
        if vtype not in (VoucherType.SALE, VoucherType.PURCHASE):
            raise BusinessRuleError("Returns can only be created against a sale or a purchase.")

        target = VoucherType.SALE_RETURN if vtype is VoucherType.SALE else VoucherType.PURCHASE_RETURN
        by_id = {line.id: line for line in original.lines}

        if lines:
            return_lines = []
            for entry in lines:
                src = by_id.get(entry.get("line_id"))
                if not src:
                    continue
                return_qty = qty(entry.get("qty", src.qty))
                if return_qty <= 0 or return_qty > src.qty:
                    raise BusinessRuleError(
                        f"Return quantity for '{src.item_name}' must be between 0 and {src.qty}."
                    )
                return_lines.append((src, return_qty))
        else:
            return_lines = [(line, line.qty) for line in original.lines]

        if not return_lines:
            raise BusinessRuleError("Nothing to return.")

        payload = VoucherCreate(
            voucher_type=target,
            voucher_date=return_date or date.today(),
            party_id=original.party_id,
            party_name=original.party_name,
            place_of_supply=original.place_of_supply,
            is_tax_inclusive=original.is_tax_inclusive,
            parent_voucher_id=original.id,
            notes=reason,
            lines=[
                VoucherLineInput(
                    item_id=src.item_id,
                    item_name=src.item_name,
                    hsn_code=src.hsn_code,
                    unit_label=src.unit_label,
                    qty=q,
                    rate=src.rate,
                    cost_price=src.cost_price,
                    discount_type=DiscountType(src.discount_type),
                    discount_value=src.discount_value,
                    tax_rate=src.tax_rate,
                    cess_rate=src.cess_rate,
                )
                for src, q in return_lines
            ],
        )
        return await self.create(payload)

    # ── listing ──────────────────────────────────────────────────
    async def list(
        self,
        params: PageParams,
        *,
        voucher_type: str | None = None,
        status: str | None = None,
        party_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        search: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        only_overdue: bool = False,
        only_unpaid: bool = False,
        source: str | None = None,
    ) -> tuple[list[Voucher], int]:
        stmt = self.base_query()
        if voucher_type:
            stmt = stmt.where(Voucher.voucher_type == voucher_type)
        if status:
            stmt = stmt.where(Voucher.status == status)
        if party_id:
            stmt = stmt.where(Voucher.party_id == party_id)
        if start_date:
            stmt = stmt.where(Voucher.voucher_date >= start_date)
        if end_date:
            stmt = stmt.where(Voucher.voucher_date <= end_date)
        if min_amount is not None:
            stmt = stmt.where(Voucher.total >= min_amount)
        if max_amount is not None:
            stmt = stmt.where(Voucher.total <= max_amount)
        if source:
            stmt = stmt.where(Voucher.source == source)
        if only_unpaid:
            stmt = stmt.where(Voucher.balance_amount > 0, Voucher.status != VoucherStatus.CANCELLED)
        if only_overdue:
            stmt = stmt.where(
                Voucher.balance_amount > 0,
                Voucher.due_date.isnot(None),
                Voucher.due_date < date.today(),
                Voucher.status != VoucherStatus.CANCELLED,
            )
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Voucher.number).like(like),
                    func.lower(func.coalesce(Voucher.party_name, "")).like(like),
                    func.lower(func.coalesce(Voucher.reference_number, "")).like(like),
                    func.lower(func.coalesce(Voucher.notes, "")).like(like),
                )
            )
        return await paginate(self.db, stmt, params, model=Voucher, default_sort="voucher_date")

    async def outstanding_for_party(self, party_id: str, *, direction: str = "receivable") -> list[Voucher]:
        """Unpaid invoices oldest-first — the FIFO order payments settle in."""
        types = (
            [VoucherType.SALE, VoucherType.PURCHASE_RETURN]
            if direction == "receivable"
            else [VoucherType.PURCHASE, VoucherType.SALE_RETURN]
        )
        stmt = (
            self.base_query()
            .where(
                Voucher.party_id == party_id,
                Voucher.voucher_type.in_([str(t) for t in types]),
                Voucher.balance_amount > 0,
                Voucher.status.notin_([VoucherStatus.CANCELLED, VoucherStatus.DRAFT]),
            )
            .order_by(Voucher.voucher_date.asc(), Voucher.created_at.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def stats(self, start: date, end: date, voucher_type: str = VoucherType.SALE) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(Voucher.total), 0),
                    func.coalesce(func.sum(Voucher.taxable_amount), 0),
                    func.coalesce(func.sum(Voucher.tax_amount), 0),
                    func.coalesce(func.sum(Voucher.profit), 0),
                    func.coalesce(func.sum(Voucher.balance_amount), 0),
                    func.count(),
                ).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.voucher_type == voucher_type,
                    Voucher.status.notin_([VoucherStatus.CANCELLED, VoucherStatus.DRAFT]),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).one()
        return {
            "total": money(row[0]),
            "taxable": money(row[1]),
            "tax": money(row[2]),
            "profit": money(row[3]),
            "outstanding": money(row[4]),
            "count": int(row[5]),
        }

    # ── line & total maths ───────────────────────────────────────
    async def _build_lines(
        self,
        voucher: Voucher,
        lines: list[VoucherLineInput],
        *,
        interstate: bool,
        inclusive: bool,
    ) -> None:
        for position, line_in in enumerate(lines):
            item: Item | None = None
            if line_in.item_id:
                item = await self.items.get(line_in.item_id)
                if item is None:
                    raise NotFoundError(
                        f"Item not found for line {position + 1}.",
                        details={"item_id": line_in.item_id},
                    )

            name = line_in.item_name or (item.name if item else "")
            if not name:
                raise BusinessRuleError(f"Line {position + 1} has no item name.")

            line_qty = qty(line_in.qty)
            rate = money(line_in.rate if line_in.rate else (item.sale_price if item else ZERO))
            if voucher.type_enum.party_kind == "supplier" and item and not line_in.rate:
                rate = money(item.purchase_price)

            gross = money(line_qty * rate)
            discount_amount = (
                pct(gross, line_in.discount_value)
                if line_in.discount_type == DiscountType.PERCENT
                else money(line_in.discount_value)
            )
            discount_amount = min(discount_amount, gross)
            net = money(gross - discount_amount)

            tax_rate = (
                D(line_in.tax_rate)
                if line_in.tax_rate is not None
                else (ZERO if (item and item.is_tax_exempt) else D(item.tax_rate) if item else ZERO)
            )
            cess_rate = D(line_in.cess_rate) if line_in.cess_rate else (D(item.cess_rate) if item else ZERO)

            # Tax-inclusive pricing can be declared at three levels: the shop
            # (BusinessSettings.prices_include_tax), the document
            # (Voucher.is_tax_inclusive), or the item itself.
            #
            # The item level was accepted by the API, stored, and returned in
            # every response — but never read here, so a shopkeeper who ticked
            # "price includes tax" on an item still got tax added on top of an
            # already tax-inclusive rate. On an 18% item quoted at 1180 the
            # customer was billed 1392: the setting looked like it worked and
            # silently overcharged instead.
            line_inclusive = inclusive or bool(item and item.price_includes_tax)

            breakdown = compute_line_tax(
                net, tax_rate, interstate=interstate, inclusive=line_inclusive,
                cess_rate=cess_rate,
            )

            cost = money(
                line_in.cost_price
                if line_in.cost_price is not None
                else (item.avg_cost or item.purchase_price) if item else ZERO
            )
            profit = (
                money((breakdown.taxable - cost * line_qty))
                if voucher.type_enum in (VoucherType.SALE, VoucherType.DELIVERY_CHALLAN)
                else ZERO
            )

            self.db.add(
                VoucherLine(
                    business_id=self.business_id,
                    voucher_id=voucher.id,
                    position=position,
                    item_id=item.id if item else None,
                    batch_id=line_in.batch_id,
                    godown_id=line_in.godown_id,
                    item_name=name,
                    description=line_in.description,
                    hsn_code=line_in.hsn_code or (item.hsn_code if item else None),
                    unit_label=line_in.unit_label or (item.unit_label if item else "Pcs"),
                    qty=line_qty,
                    free_qty=qty(line_in.free_qty),
                    rate=rate,
                    mrp=line_in.mrp or (item.mrp if item else None),
                    cost_price=cost,
                    discount_type=str(line_in.discount_type),
                    discount_value=money(line_in.discount_value),
                    discount_amount=discount_amount,
                    taxable_amount=breakdown.taxable,
                    tax_rate=tax_rate,
                    cgst_amount=breakdown.cgst,
                    sgst_amount=breakdown.sgst,
                    igst_amount=breakdown.igst,
                    cess_rate=cess_rate,
                    cess_amount=breakdown.cess,
                    tax_amount=breakdown.total_tax,
                    total=breakdown.total,
                    line_profit=profit,
                    serial_numbers=line_in.serial_numbers or [],
                )
            )
        await self.db.flush()
        await self.db.refresh(voucher, ["lines"])

    def _compute_totals(
        self, voucher: Voucher, cfg: BusinessSettings, *, buyer_registered: bool = True
    ) -> None:
        lines = voucher.lines
        subtotal = money(sum((line.qty * line.rate for line in lines), ZERO))
        line_discounts = money(sum((line.discount_amount for line in lines), ZERO))
        taxable = money(sum((line.taxable_amount for line in lines), ZERO))

        # A document-level discount applies on top of line discounts.
        doc_discount = (
            pct(taxable, voucher.discount_value)
            if voucher.discount_type == DiscountType.PERCENT
            else money(voucher.discount_value)
        )
        doc_discount = min(doc_discount, taxable)

        # Spread the document discount proportionally so tax stays correct.
        if doc_discount > 0 and taxable > 0:
            ratio = (taxable - doc_discount) / taxable
            cgst = money(sum((line.cgst_amount for line in lines), ZERO) * ratio)
            sgst = money(sum((line.sgst_amount for line in lines), ZERO) * ratio)
            igst = money(sum((line.igst_amount for line in lines), ZERO) * ratio)
            cess = money(sum((line.cess_amount for line in lines), ZERO) * ratio)
            net_taxable = money(taxable - doc_discount)
        else:
            cgst = money(sum((line.cgst_amount for line in lines), ZERO))
            sgst = money(sum((line.sgst_amount for line in lines), ZERO))
            igst = money(sum((line.igst_amount for line in lines), ZERO))
            cess = money(sum((line.cess_amount for line in lines), ZERO))
            net_taxable = taxable

        tax_total = money(cgst + sgst + igst + cess)

        # Pakistani further tax: charged on top when the buyer has no sales tax
        # registration. A shop that has never heard of it under-charges every
        # walk-in customer and is assessed for the difference years later. Only
        # on outward supplies — a shop does not levy it on its own purchases.
        further = ZERO
        if (
            cfg.fbr_enabled
            and cfg.further_tax_enabled
            and not buyer_registered
            and voucher.voucher_type in (VoucherType.SALE, VoucherType.SALE_RETURN)
        ):
            further = pct(net_taxable, cfg.further_tax_rate)

        charges = money(voucher.shipping_charge + voucher.packaging_charge + voucher.other_charge)
        raw_total = money(net_taxable + tax_total + further + charges)

        round_off = ZERO
        if cfg.auto_round_off:
            rounded = rupee(raw_total)
            round_off = money(rounded - raw_total)
            raw_total = money(rounded)

        voucher.subtotal = subtotal
        voucher.discount_amount = money(line_discounts + doc_discount)
        voucher.taxable_amount = net_taxable
        voucher.cgst_amount = cgst
        voucher.sgst_amount = sgst
        voucher.igst_amount = igst
        voucher.cess_amount = cess
        voucher.tax_amount = tax_total
        voucher.further_tax_amount = further
        voucher.round_off = round_off
        voucher.total = raw_total
        voucher.balance_amount = money(raw_total - voucher.paid_amount)
        voucher.profit = money(sum((line.line_profit for line in lines), ZERO) - doc_discount)

    # ── side effects ─────────────────────────────────────────────
    async def _apply_stock(self, voucher: Voucher, vtype: VoucherType) -> None:
        if not vtype.affects_stock:
            return
        # Sales and purchase-returns take stock out; purchases and sale-returns bring it in.
        outward = vtype in (VoucherType.SALE, VoucherType.PURCHASE_RETURN, VoucherType.DELIVERY_CHALLAN)
        for line in voucher.lines:
            if not line.item_id:
                continue
            item = await self.items.get(line.item_id)
            if item is None:
                continue
            movement_qty = qty(line.qty + line.free_qty)
            await self.stock.record(
                item,
                qty_delta=-movement_qty if outward else movement_qty,
                movement=StockMovement.OUT if outward else StockMovement.IN,
                rate=line.cost_price if outward else line.rate,
                entry_date=datetime.combine(voucher.voucher_date, datetime.min.time()),
                reference_type="voucher",
                reference_id=voucher.id,
                reference_number=voucher.number,
                party_id=voucher.party_id,
                batch_id=line.batch_id,
                godown_id=line.godown_id,
            )
            # Which pieces left, not just how many. A handset sold by its IMEI
            # that stays marked in stock can be sold again to somebody else,
            # and when the first customer comes back with a fault the shop has
            # no record it ever went out.
            if outward and line.serial_numbers:
                await self.serials.reserve_for_sale(
                    line.item_id,
                    list(line.serial_numbers),
                    voucher_id=voucher.id,
                    sale_price=line.rate,
                )

            if vtype is VoucherType.SALE:
                item.total_sold_qty = qty(item.total_sold_qty + line.qty)
                item.total_sold_value = money(item.total_sold_value + line.total)

    async def _reverse_stock(self, voucher: Voucher) -> None:
        if voucher.type_enum.affects_stock:
            await self.stock.reverse("voucher", voucher.id)
            # The pieces come back with the stock. Left marked sold they would
            # be unsellable for good — stock the shop owns and cannot shift.
            await self.serials.release(voucher.id)

    async def _apply_ledger(self, voucher: Voucher, vtype: VoucherType, party: Party | None) -> None:
        if not vtype.affects_ledger or not party:
            return
        delta = voucher.total if vtype.is_outward else -voucher.total
        party.balance = money(party.balance + delta)
        party.last_transaction_at = utcnow()
        party.transaction_count = (party.transaction_count or 0) + 1
        if vtype is VoucherType.SALE:
            party.total_sales = money(party.total_sales + voucher.total)
        elif vtype is VoucherType.PURCHASE:
            party.total_purchases = money(party.total_purchases + voucher.total)
        party.bump_revision()

    async def _reverse_ledger(self, voucher: Voucher) -> None:
        vtype = voucher.type_enum
        if not vtype.affects_ledger or not voucher.party_id:
            return
        party = await self.parties.get(voucher.party_id)
        if not party:
            return
        delta = voucher.total if vtype.is_outward else -voucher.total
        party.balance = money(party.balance - delta)
        party.transaction_count = max(0, (party.transaction_count or 1) - 1)
        if vtype is VoucherType.SALE:
            party.total_sales = money(max(ZERO, party.total_sales - voucher.total))
        elif vtype is VoucherType.PURCHASE:
            party.total_purchases = money(max(ZERO, party.total_purchases - voucher.total))
        party.bump_revision()

    async def _record_inline_payment(self, voucher: Voucher, payment_in, party: Party | None) -> None:
        from app.services.payment_service import PaymentService  # circular at module level

        amount = money(payment_in.amount)
        if amount <= 0:
            return
        if amount > voucher.total:
            raise BusinessRuleError(
                "Payment cannot exceed the invoice total.",
                details={"amount": str(amount), "total": str(voucher.total)},
            )
        direction = (
            PaymentDirection.IN if voucher.type_enum.party_kind == "customer" else PaymentDirection.OUT
        )
        await PaymentService(self.db, self.actor).create_raw(
            direction=direction,
            amount=amount,
            party=party,
            mode=payment_in.mode,
            account_id=payment_in.account_id,
            reference_number=payment_in.reference_number,
            payment_date=payment_in.payment_date or voucher.voucher_date,
            notes=payment_in.notes or f"Against {voucher.number}",
            allocations=[{"voucher_id": voucher.id, "amount": amount}],
            source=voucher.source,
        )

    # ── helpers ──────────────────────────────────────────────────
    async def settings(self) -> BusinessSettings:
        if self._settings is None:
            row = (
                await self.db.execute(
                    select(BusinessSettings).where(BusinessSettings.business_id == self.business_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = BusinessSettings(business_id=self.business_id)
                self.db.add(row)
                await self.db.flush()
            self._settings = row
        return self._settings

    async def business(self) -> Business:
        if self._business is None:
            self._business = (
                await self.db.execute(select(Business).where(Business.id == self.business_id))
            ).scalar_one()
        return self._business

    async def _resolve_party(self, payload: VoucherCreate, vtype: VoucherType) -> Party | None:
        if payload.party_id:
            return await self.parties.get_or_404(payload.party_id)
        if payload.party_name and vtype.affects_ledger:
            party, _created = await self.parties.resolve_or_create(
                payload.party_name, party_type=vtype.party_kind, phone=payload.party_phone
            )
            return party
        return None

    def _is_interstate(self, biz: Business, party: Party | None, place_of_supply: str | None) -> bool:
        pos = place_of_supply or (party.state_code if party else None)
        return is_interstate(biz.state_code, pos)

    def _default_due_date(
        self, vdate: date, party: Party | None, cfg: BusinessSettings, vtype: VoucherType
    ) -> date | None:
        if not vtype.affects_ledger:
            return None
        days = (party.credit_days if party and party.credit_days is not None else cfg.default_due_days)
        return vdate + timedelta(days=int(days or 0))

    async def _assert_number_free(self, vtype: VoucherType, number: str) -> None:
        existing = (
            await self.db.execute(
                self.base_query(include_deleted=True).where(
                    Voucher.voucher_type == str(vtype), Voucher.number == number
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(
                f"Document number '{number}' is already in use.",
                details={"number": number, "existing_id": existing.id},
            )
