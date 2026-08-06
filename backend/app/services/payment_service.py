"""Payments, FIFO allocation across invoices, and cash/bank accounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.money import ZERO, D, money
from app.core.pagination import PageParams, paginate
from app.models.enums import PaymentDirection, VoucherStatus, VoucherType
from app.models.party import Party
from app.models.payment import Account, Payment, PaymentAllocation
from app.models.voucher import Voucher
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.services.base import ActorContext, BaseService, stamp_sync
from app.services.numbering_service import NumberingService
from app.services.party_service import PartyService


class PaymentService(BaseService[Payment]):
    model = Payment
    entity_name = "payment"

    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        super().__init__(db, actor)
        self.parties = PartyService(db, actor)
        self.numbering = NumberingService(db, self.business_id)

    # ── create ───────────────────────────────────────────────────
    async def create(self, payload: PaymentCreate) -> Payment:
        if payload.client_uuid:
            existing = await self.get_by_client_uuid(payload.client_uuid)
            if existing:
                return existing

        party: Party | None = None
        if payload.party_id:
            party = await self.parties.get_or_404(payload.party_id)
        elif payload.party_name:
            party, _ = await self.parties.resolve_or_create(
                payload.party_name,
                party_type="customer" if payload.direction == PaymentDirection.IN else "supplier",
            )

        allocations = [{"voucher_id": a.voucher_id, "amount": a.amount} for a in payload.allocations]
        return await self.create_raw(
            direction=str(payload.direction),
            amount=money(payload.amount),
            party=party,
            mode=str(payload.mode),
            account_id=payload.account_id,
            reference_number=payload.reference_number,
            cheque_date=payload.cheque_date,
            payment_date=payload.payment_date or date.today(),
            notes=payload.notes,
            discount_given=money(payload.discount_given),
            allocations=allocations,
            auto_allocate=payload.auto_allocate and not allocations,
            number=payload.number,
            client_uuid=payload.client_uuid,
            source=payload.source,
        )

    async def create_raw(
        self,
        *,
        direction: str,
        amount: Decimal,
        party: Party | None,
        mode: str = "cash",
        account_id: str | None = None,
        reference_number: str | None = None,
        cheque_date: date | None = None,
        payment_date: date | None = None,
        notes: str | None = None,
        discount_given: Decimal = ZERO,
        allocations: list[dict[str, Any]] | None = None,
        auto_allocate: bool = False,
        number: str | None = None,
        client_uuid: str | None = None,
        source: str = "manual",
    ) -> Payment:
        """The single code path every payment goes through — inline invoice
        payments, settlements and the AI tool all land here."""
        amount = money(amount)
        if amount <= 0:
            raise BusinessRuleError("Payment amount must be greater than zero.")

        pay_date = payment_date or date.today()
        series = "payment_in" if direction == PaymentDirection.IN else "payment_out"
        if number:
            await self.numbering.reserve_explicit(series, number, pay_date)
        else:
            number, _seq = await self.numbering.next_number(series, on_date=pay_date)

        payment = Payment(
            business_id=self.business_id,
            number=number,
            direction=direction,
            payment_date=pay_date,
            party_id=party.id if party else None,
            party_name=party.name if party else None,
            amount=amount,
            discount_given=money(discount_given),
            allocated_amount=ZERO,
            unallocated_amount=amount,
            mode=mode,
            account_id=account_id or await self._default_account_id(mode),
            reference_number=reference_number,
            cheque_date=cheque_date,
            cheque_status="pending" if mode == "cheque" else None,
            notes=notes,
            source=source,
            created_by=self.actor.user_id,
        )
        stamp_sync(payment, self.actor, client_uuid=client_uuid)
        self.db.add(payment)
        await self.db.flush()

        targets = list(allocations or [])
        if auto_allocate and party:
            targets = await self._fifo_targets(party.id, direction, amount + money(discount_given))

        await self._apply_allocations(payment, targets)

        if party:
            delta = -(amount + money(discount_given)) if direction == PaymentDirection.IN else (amount + money(discount_given))
            party.balance = money(party.balance + delta)
            party.bump_revision()

        # A cheque is a promise, not money. The account only moves when the bank
        # settles it, which ChequeService does on clearing — otherwise a bounced
        # cheque leaves a shop believing it holds money it never received. The
        # party's balance still moves here, because the debt genuinely is
        # considered paid the moment the cheque changes hands.
        if payment.cheque_status not in ("pending", "deposited"):
            await self._move_account_balance(
                payment.account_id, amount if direction == PaymentDirection.IN else -amount
            )

        await self.db.flush()
        await self.track("create", payment, label=payment.number)
        self.log("payment.created", payment_id=payment.id, amount=str(amount), direction=direction)
        return payment

    # ── update / delete ──────────────────────────────────────────
    async def update(self, payment_id: str, payload: PaymentUpdate) -> Payment:
        payment = await self.get_or_404(payment_id)
        data = payload.model_dump(exclude_unset=True)

        old_amount = payment.amount
        old_account = payment.account_id

        if "allocations" in data and data["allocations"] is not None:
            await self._clear_allocations(payment)

        if "amount" in data and data["amount"] is not None:
            new_amount = money(data["amount"])
            if payment.party_id:
                party = await self.parties.get(payment.party_id)
                if party:
                    shift = new_amount - old_amount
                    party.balance = money(
                        party.balance + (-shift if payment.direction == PaymentDirection.IN else shift)
                    )
                    party.bump_revision()
            payment.amount = new_amount
            payment.unallocated_amount = money(new_amount - payment.allocated_amount)

        changes = self.apply_fields(
            payment,
            {k: v for k, v in data.items() if k not in ("allocations", "amount")},
        )

        if data.get("allocations"):
            await self._apply_allocations(
                payment, [{"voucher_id": a["voucher_id"], "amount": a["amount"]} for a in data["allocations"]]
            )

        if payment.account_id != old_account:
            signed = payment.amount if payment.direction == PaymentDirection.IN else -payment.amount
            await self._move_account_balance(old_account, -signed)
            await self._move_account_balance(payment.account_id, signed)

        payment.updated_by = self.actor.user_id
        payment.bump_revision()
        await self.db.flush()
        await self.track("update", payment, changes=changes, label=payment.number)
        return payment

    async def delete(self, payment_id: str) -> None:
        payment = await self.get_or_404(payment_id)
        await self._clear_allocations(payment)

        if payment.party_id:
            party = await self.parties.get(payment.party_id)
            if party:
                restore = payment.amount + payment.discount_given
                party.balance = money(
                    party.balance + (restore if payment.direction == PaymentDirection.IN else -restore)
                )
                party.bump_revision()

        signed = payment.amount if payment.direction == PaymentDirection.IN else -payment.amount
        await self._move_account_balance(payment.account_id, -signed)

        await self.soft_delete(payment, label=payment.number)

    # ── settlement ("Ahmed ne 5000 diye") ────────────────────────
    async def settle_party(
        self,
        party_id: str,
        amount: Decimal,
        *,
        direction: str = PaymentDirection.IN,
        mode: str = "cash",
        account_id: str | None = None,
        payment_date: date | None = None,
        notes: str | None = None,
        discount_given: Decimal = ZERO,
        source: str = "manual",
    ) -> dict[str, Any]:
        party = await self.parties.get_or_404(party_id)
        payment = await self.create_raw(
            direction=direction,
            amount=money(amount),
            party=party,
            mode=mode,
            account_id=account_id,
            payment_date=payment_date,
            notes=notes,
            discount_given=discount_given,
            auto_allocate=True,
            source=source,
        )
        settled = [
            {
                "voucher_id": a.voucher_id,
                "voucher_number": a.voucher_number,
                "amount": money(a.amount),
            }
            for a in payment.allocations
        ]
        return {
            "payment": payment,
            "settled_vouchers": settled,
            "remaining_credit": money(payment.unallocated_amount),
            "party_balance_after": money(party.balance),
        }

    # ── listing ──────────────────────────────────────────────────
    async def list(
        self,
        params: PageParams,
        *,
        direction: str | None = None,
        party_id: str | None = None,
        mode: str | None = None,
        account_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        search: str | None = None,
    ) -> tuple[list[Payment], int]:
        stmt = self.base_query()
        if direction:
            stmt = stmt.where(Payment.direction == direction)
        if party_id:
            stmt = stmt.where(Payment.party_id == party_id)
        if mode:
            stmt = stmt.where(Payment.mode == mode)
        if account_id:
            stmt = stmt.where(Payment.account_id == account_id)
        if start_date:
            stmt = stmt.where(Payment.payment_date >= start_date)
        if end_date:
            stmt = stmt.where(Payment.payment_date <= end_date)
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Payment.number).like(like),
                    func.lower(func.coalesce(Payment.party_name, "")).like(like),
                    func.lower(func.coalesce(Payment.reference_number, "")).like(like),
                )
            )
        return await paginate(self.db, stmt, params, model=Payment, default_sort="payment_date")

    async def totals(self, start: date, end: date, direction: str = PaymentDirection.IN) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.direction == direction,
                    Payment.payment_date >= start,
                    Payment.payment_date <= end,
                )
            )
        ).scalar_one()
        return money(value)

    # ── internals ────────────────────────────────────────────────
    async def _fifo_targets(self, party_id: str, direction: str, budget: Decimal) -> list[dict[str, Any]]:
        """Oldest unpaid invoice first — how a shopkeeper actually applies cash."""
        types = (
            [VoucherType.SALE, VoucherType.PURCHASE_RETURN]
            if direction == PaymentDirection.IN
            else [VoucherType.PURCHASE, VoucherType.SALE_RETURN]
        )
        vouchers = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.party_id == party_id,
                    Voucher.voucher_type.in_([str(t) for t in types]),
                    Voucher.balance_amount > 0,
                    Voucher.status.notin_([VoucherStatus.CANCELLED, VoucherStatus.DRAFT]),
                )
                .order_by(Voucher.voucher_date.asc(), Voucher.created_at.asc())
            )
        ).scalars().all()

        targets: list[dict[str, Any]] = []
        remaining = money(budget)
        for v in vouchers:
            if remaining <= 0:
                break
            take = min(remaining, money(v.balance_amount))
            targets.append({"voucher_id": v.id, "amount": take})
            remaining = money(remaining - take)
        return targets

    async def _apply_allocations(self, payment: Payment, targets: list[dict[str, Any]]) -> None:
        allocated = ZERO
        for target in targets:
            amount = money(target["amount"])
            if amount <= 0:
                continue
            voucher = (
                await self.db.execute(
                    select(Voucher).where(
                        Voucher.id == target["voucher_id"],
                        Voucher.business_id == self.business_id,
                        Voucher.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if voucher is None:
                raise NotFoundError("Invoice not found.", details={"voucher_id": target["voucher_id"]})
            if amount > voucher.balance_amount + Decimal("0.01"):
                raise BusinessRuleError(
                    f"Cannot allocate {amount} to {voucher.number}; only {voucher.balance_amount} is due.",
                    details={"voucher_number": voucher.number, "due": str(voucher.balance_amount)},
                )

            self.db.add(
                PaymentAllocation(
                    business_id=self.business_id,
                    payment_id=payment.id,
                    voucher_id=voucher.id,
                    voucher_number=voucher.number,
                    amount=amount,
                )
            )
            voucher.paid_amount = money(voucher.paid_amount + amount)
            voucher.balance_amount = money(voucher.total - voucher.paid_amount)
            voucher.status = voucher.compute_status()
            voucher.bump_revision()
            allocated = money(allocated + amount)

        payment.allocated_amount = money(payment.allocated_amount + allocated)
        payment.unallocated_amount = money(payment.amount - payment.allocated_amount)
        await self.db.flush()
        await self.db.refresh(payment, ["allocations"])

    async def _clear_allocations(self, payment: Payment) -> None:
        rows = (
            await self.db.execute(
                select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
            )
        ).scalars().all()
        for alloc in rows:
            voucher = (
                await self.db.execute(select(Voucher).where(Voucher.id == alloc.voucher_id))
            ).scalar_one_or_none()
            if voucher:
                voucher.paid_amount = money(max(ZERO, voucher.paid_amount - alloc.amount))
                voucher.balance_amount = money(voucher.total - voucher.paid_amount)
                voucher.status = voucher.compute_status()
                voucher.bump_revision()
            await self.db.delete(alloc)
        payment.allocated_amount = ZERO
        payment.unallocated_amount = payment.amount
        await self.db.flush()

    async def _default_account_id(self, mode: str) -> str | None:
        wanted = "cash" if mode == "cash" else "bank"
        row = (
            await self.db.execute(
                select(Account).where(
                    Account.business_id == self.business_id,
                    Account.is_deleted.is_(False),
                    Account.is_active.is_(True),
                    or_(Account.account_type == wanted, Account.is_default.is_(True)),
                ).order_by(Account.is_default.desc()).limit(1)
            )
        ).scalar_one_or_none()
        return row.id if row else None

    async def _move_account_balance(self, account_id: str | None, delta: Decimal) -> None:
        if not account_id:
            return
        account = (
            await self.db.execute(
                select(Account).where(Account.id == account_id, Account.business_id == self.business_id)
            )
        ).scalar_one_or_none()
        if account:
            account.balance = money(account.balance + D(delta))


class AccountService(BaseService[Account]):
    model = Account
    entity_name = "account"

    async def create(self, data: dict[str, Any]) -> Account:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        opening = money(data.get("opening_balance", ZERO) or ZERO)
        account = Account(
            business_id=self.business_id,
            balance=opening,
            **{k: v for k, v in data.items() if hasattr(Account, k)},
        )
        stamp_sync(account, self.actor, client_uuid=client_uuid)
        if account.is_default:
            await self._clear_default()
        self.db.add(account)
        await self.db.flush()
        await self.track("create", account, label=account.name)
        return account

    async def list_all(self) -> list[Account]:
        return list(
            (
                await self.db.execute(
                    self.base_query().where(Account.is_active.is_(True)).order_by(
                        Account.is_default.desc(), Account.name
                    )
                )
            ).scalars().all()
        )

    async def cash_and_bank(self) -> tuple[Decimal, Decimal]:
        rows = await self.list_all()
        cash = money(sum((a.balance for a in rows if a.account_type == "cash"), ZERO))
        bank = money(sum((a.balance for a in rows if a.account_type != "cash"), ZERO))
        return cash, bank

    async def _clear_default(self) -> None:
        for row in (await self.db.execute(self.base_query().where(Account.is_default.is_(True)))).scalars():
            row.is_default = False
