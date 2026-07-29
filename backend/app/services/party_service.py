"""Party CRUD, ledger, balances and ageing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError
from app.core.money import ZERO, D, money
from app.core.pagination import PageParams, paginate
from app.models.enums import PartyType, PaymentDirection, VoucherStatus, VoucherType
from app.models.party import Party, PartyGroup
from app.models.payment import Payment, PaymentAllocation
from app.models.voucher import Voucher
from app.schemas.party import LedgerEntry, PartyCreate, PartyUpdate
from app.services.base import ActorContext, BaseService, stamp_sync
from app.utils.strings import normalise, rank_matches


class PartyService(BaseService[Party]):
    model = Party
    entity_name = "party"

    # ── CRUD ─────────────────────────────────────────────────────
    async def create(self, payload: PartyCreate | dict[str, Any]) -> Party:
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        if client_uuid:
            existing = await self.get_by_client_uuid(client_uuid)
            if existing:  # idempotent replay of an offline create
                return existing

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Party name is required.")
        if await self._name_taken(name):
            raise ConflictError(
                f"A party named '{name}' already exists.",
                details={"field": "name", "suggestion": f"{name} 2"},
            )

        opening = money(data.pop("opening_balance", ZERO) or ZERO)
        party = Party(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            opening_balance=opening,
            balance=opening,
            **{k: v for k, v in data.items() if hasattr(Party, k)},
        )
        stamp_sync(party, self.actor, client_uuid=client_uuid)
        self.db.add(party)
        await self.db.flush()
        await self.track("create", party, label=party.name)
        return party

    async def update(self, party_id: str, payload: PartyUpdate | dict[str, Any]) -> Party:
        party = await self.get_or_404(party_id)
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)

        new_name = data.get("name")
        if new_name and normalise(new_name) != normalise(party.name) and await self._name_taken(new_name):
            raise ConflictError(f"A party named '{new_name}' already exists.")

        # Changing the opening balance shifts the whole ledger by the delta.
        if "opening_balance" in data:
            delta = money(data["opening_balance"]) - party.opening_balance
            party.balance = money(party.balance + delta)

        changes = self.apply_fields(party, data)
        if changes:
            party.updated_by = self.actor.user_id
            party.bump_revision()
            await self.track("update", party, changes=changes, label=party.name)
        return party

    async def delete(self, party_id: str) -> None:
        party = await self.get_or_404(party_id)
        txn_count = (
            await self.db.execute(
                select(func.count())
                .select_from(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.party_id == party_id,
                    Voucher.is_deleted.is_(False),
                )
            )
        ).scalar_one()
        if txn_count:
            raise BusinessRuleError(
                f"'{party.name}' has {txn_count} transaction(s) and cannot be deleted. "
                "Mark them inactive instead.",
                details={"transaction_count": int(txn_count), "party_id": party_id},
            )
        await self.soft_delete(party, label=party.name)

    # ── listing / search ─────────────────────────────────────────
    async def list(
        self,
        params: PageParams,
        *,
        search: str | None = None,
        party_type: str | None = None,
        group_id: str | None = None,
        only_with_balance: bool = False,
        only_receivable: bool = False,
        only_payable: bool = False,
        is_active: bool | None = None,
    ) -> tuple[list[Party], int]:
        stmt = self.base_query()
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Party.name).like(like),
                    func.lower(func.coalesce(Party.phone, "")).like(like),
                    func.lower(func.coalesce(Party.email, "")).like(like),
                    func.lower(func.coalesce(Party.contact_person, "")).like(like),
                    func.lower(func.coalesce(Party.gstin, "")).like(like),
                )
            )
        if party_type and party_type != "all":
            stmt = stmt.where(
                or_(Party.party_type == party_type, Party.party_type == PartyType.BOTH)
            )
        if group_id:
            stmt = stmt.where(Party.group_id == group_id)
        if is_active is not None:
            stmt = stmt.where(Party.is_active.is_(is_active))
        if only_with_balance:
            stmt = stmt.where(Party.balance != 0)
        if only_receivable:
            stmt = stmt.where(Party.balance > 0)
        if only_payable:
            stmt = stmt.where(Party.balance < 0)

        return await paginate(self.db, stmt, params, model=Party, default_sort="name")

    async def search_by_name(self, query: str, limit: int = 5) -> list[tuple[Party, float]]:
        """Fuzzy lookup used by the AI: 'ahmad traders' → the real Ahmed Traders row."""
        if not query or not query.strip():
            return []
        like = f"%{query.strip().lower()[:40]}%"
        exact = (
            await self.db.execute(
                self.base_query().where(
                    or_(
                        func.lower(Party.name).like(like),
                        func.lower(func.coalesce(Party.phone, "")).like(like),
                    )
                ).limit(25)
            )
        ).scalars().all()

        pool = list(exact)
        if len(pool) < 3:  # widen the net before giving up
            pool += list(
                (await self.db.execute(self.base_query().limit(400))).scalars().all()
            )

        by_id = {p.id: p for p in pool}
        ranked = rank_matches(query, [(p.id, p.name) for p in by_id.values()], limit=limit)
        return [(by_id[pid], score) for pid, _n, score in ranked]

    async def resolve_or_create(
        self, name: str, *, party_type: str = PartyType.CUSTOMER, phone: str | None = None
    ) -> tuple[Party, bool]:
        """Used by the AI/OCR path: find the party by name, else create it."""
        if phone:
            hit = (
                await self.db.execute(self.base_query().where(Party.phone == phone).limit(1))
            ).scalar_one_or_none()
            if hit:
                return hit, False
        matches = await self.search_by_name(name, limit=1)
        if matches and matches[0][1] >= 0.82:
            return matches[0][0], False
        created = await self.create(
            PartyCreate(name=name.strip(), party_type=party_type, phone=phone)  # type: ignore[arg-type]
        )
        return created, True

    # ── money ────────────────────────────────────────────────────
    async def adjust_balance(self, party_id: str, delta: Decimal) -> Decimal:
        """Positive delta increases what the party owes us."""
        party = await self.get_or_404(party_id)
        party.balance = money(D(party.balance) + D(delta))
        party.bump_revision()
        return party.balance

    async def recalculate_balance(self, party_id: str) -> Decimal:
        """Rebuild the balance from source rows — the repair path when things drift."""
        party = await self.get_or_404(party_id)

        sale_total, sale_count = await self._voucher_totals(
            party_id, [VoucherType.SALE, VoucherType.PURCHASE_RETURN]
        )
        purchase_total, purchase_count = await self._voucher_totals(
            party_id, [VoucherType.PURCHASE, VoucherType.SALE_RETURN]
        )
        received = await self._payment_total(party_id, PaymentDirection.IN)
        paid_out = await self._payment_total(party_id, PaymentDirection.OUT)

        party.balance = money(party.opening_balance + sale_total - purchase_total - received + paid_out)
        party.total_sales = money(sale_total)
        party.total_purchases = money(purchase_total)
        party.transaction_count = int(sale_count + purchase_count)
        party.bump_revision()
        return party.balance

    async def ledger(
        self, party_id: str, *, start: date | None = None, end: date | None = None
    ) -> dict[str, Any]:
        party = await self.get_or_404(party_id)

        v_stmt = select(Voucher).where(
            Voucher.business_id == self.business_id,
            Voucher.party_id == party_id,
            Voucher.is_deleted.is_(False),
            Voucher.status != VoucherStatus.CANCELLED,
            Voucher.voucher_type.in_(
                [VoucherType.SALE, VoucherType.PURCHASE, VoucherType.SALE_RETURN, VoucherType.PURCHASE_RETURN]
            ),
        )
        p_stmt = select(Payment).where(
            Payment.business_id == self.business_id,
            Payment.party_id == party_id,
            Payment.is_deleted.is_(False),
        )
        if start:
            v_stmt = v_stmt.where(Voucher.voucher_date >= start)
            p_stmt = p_stmt.where(Payment.payment_date >= start)
        if end:
            v_stmt = v_stmt.where(Voucher.voucher_date <= end)
            p_stmt = p_stmt.where(Payment.payment_date <= end)

        vouchers = (await self.db.execute(v_stmt)).scalars().all()
        payments = (await self.db.execute(p_stmt)).scalars().all()

        rows: list[tuple[date, int, LedgerEntry]] = []
        for v in vouchers:
            debit = v.total if v.voucher_type in (VoucherType.SALE, VoucherType.PURCHASE_RETURN) else ZERO
            credit = v.total if v.voucher_type in (VoucherType.PURCHASE, VoucherType.SALE_RETURN) else ZERO
            rows.append((
                v.voucher_date, 0,
                LedgerEntry(
                    date=v.voucher_date,
                    entry_type=v.voucher_type,
                    reference_id=v.id,
                    reference_number=v.number,
                    description=_voucher_label(v),
                    debit=money(debit),
                    credit=money(credit),
                ),
            ))
        for p in payments:
            received = p.direction == PaymentDirection.IN
            rows.append((
                p.payment_date, 1,
                LedgerEntry(
                    date=p.payment_date,
                    entry_type=f"payment_{p.direction}",
                    reference_id=p.id,
                    reference_number=p.number,
                    description=f"Payment {'received' if received else 'made'} ({p.mode})",
                    debit=ZERO if received else money(p.amount),
                    credit=money(p.amount) if received else ZERO,
                ),
            ))

        rows.sort(key=lambda r: (r[0], r[1]))

        opening = await self._opening_balance(party, start)
        running = opening
        entries: list[LedgerEntry] = []
        if start:
            entries.append(
                LedgerEntry(
                    date=start, entry_type="opening", description="Opening balance",
                    debit=opening if opening > 0 else ZERO,
                    credit=-opening if opening < 0 else ZERO,
                    balance=opening,
                )
            )
        for _d, _o, entry in rows:
            running = money(running + entry.debit - entry.credit)
            entry.balance = running
            entries.append(entry)

        return {
            "party": party,
            "opening_balance": opening,
            "closing_balance": running,
            "total_debit": money(sum((e.debit for e in entries), ZERO)),
            "total_credit": money(sum((e.credit for e in entries), ZERO)),
            "entries": entries,
            "start_date": start,
            "end_date": end,
        }

    async def ageing(self, *, as_of: date | None = None, receivable: bool = True) -> dict[str, Any]:
        """Bucketed outstanding by how long the invoice has been due."""
        ref = as_of or date.today()
        types = [VoucherType.SALE] if receivable else [VoucherType.PURCHASE]
        stmt = (
            select(Voucher)
            .where(
                Voucher.business_id == self.business_id,
                Voucher.is_deleted.is_(False),
                Voucher.voucher_type.in_(types),
                Voucher.balance_amount > 0,
                Voucher.status != VoucherStatus.CANCELLED,
                Voucher.voucher_date <= ref,
            )
        )
        vouchers = (await self.db.execute(stmt)).scalars().all()

        buckets = {"current": ZERO, "1-30": ZERO, "31-60": ZERO, "61-90": ZERO, "90+": ZERO}
        counts = dict.fromkeys(buckets, 0)
        per_party: dict[str, dict[str, Any]] = {}

        for v in vouchers:
            due = v.due_date or v.voucher_date
            overdue_days = (ref - due).days
            key = (
                "current" if overdue_days <= 0
                else "1-30" if overdue_days <= 30
                else "31-60" if overdue_days <= 60
                else "61-90" if overdue_days <= 90
                else "90+"
            )
            amount = money(v.balance_amount)
            buckets[key] += amount
            counts[key] += 1

            pid = v.party_id or "walk-in"
            slot = per_party.setdefault(
                pid,
                {
                    "party_id": v.party_id, "party_name": v.party_name or "Walk-in",
                    "total": ZERO, "invoice_count": 0, "oldest_due_date": due,
                    **dict.fromkeys(buckets, ZERO),
                },
            )
            slot["total"] += amount
            slot[key] += amount
            slot["invoice_count"] += 1
            slot["oldest_due_date"] = min(slot["oldest_due_date"], due)

        parties = sorted(per_party.values(), key=lambda r: r["total"], reverse=True)
        return {
            "as_of": ref,
            "direction": "receivable" if receivable else "payable",
            "total": money(sum(buckets.values(), ZERO)),
            "buckets": [
                {"label": k, "amount": money(v), "count": counts[k]} for k, v in buckets.items()
            ],
            "parties": parties,
        }

    async def top_parties(self, limit: int = 5, *, by: str = "sales") -> list[dict[str, Any]]:
        column = Party.total_sales if by == "sales" else Party.balance
        rows = (
            await self.db.execute(
                self.base_query().where(column > 0).order_by(column.desc()).limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": p.id, "name": p.name, "phone": p.phone,
                "total_sales": money(p.total_sales), "balance": money(p.balance),
                "transaction_count": p.transaction_count,
            }
            for p in rows
        ]

    # ── internals ────────────────────────────────────────────────
    async def _name_taken(self, name: str) -> bool:
        existing = (
            await self.db.execute(
                self.base_query().where(func.lower(Party.name) == name.strip().lower()).limit(1)
            )
        ).scalar_one_or_none()
        return existing is not None

    async def _voucher_totals(self, party_id: str, types: list[str]) -> tuple[Decimal, int]:
        row = (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.total), 0), func.count()).where(
                    Voucher.business_id == self.business_id,
                    Voucher.party_id == party_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status != VoucherStatus.CANCELLED,
                    Voucher.voucher_type.in_(types),
                )
            )
        ).one()
        return D(row[0]), int(row[1])

    async def _payment_total(self, party_id: str, direction: str) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount + Payment.discount_given), 0)).where(
                    Payment.business_id == self.business_id,
                    Payment.party_id == party_id,
                    Payment.direction == direction,
                    Payment.is_deleted.is_(False),
                )
            )
        ).scalar_one()
        return D(value)

    async def _opening_balance(self, party: Party, start: date | None) -> Decimal:
        if not start:
            return money(party.opening_balance)
        prior_sales, _ = await self._voucher_totals_before(
            party.id, [VoucherType.SALE, VoucherType.PURCHASE_RETURN], start
        )
        prior_purch, _ = await self._voucher_totals_before(
            party.id, [VoucherType.PURCHASE, VoucherType.SALE_RETURN], start
        )
        prior_in = await self._payment_total_before(party.id, PaymentDirection.IN, start)
        prior_out = await self._payment_total_before(party.id, PaymentDirection.OUT, start)
        return money(party.opening_balance + prior_sales - prior_purch - prior_in + prior_out)

    async def _voucher_totals_before(
        self, party_id: str, types: list[str], before: date
    ) -> tuple[Decimal, int]:
        row = (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.total), 0), func.count()).where(
                    Voucher.business_id == self.business_id,
                    Voucher.party_id == party_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status != VoucherStatus.CANCELLED,
                    Voucher.voucher_type.in_(types),
                    Voucher.voucher_date < before,
                )
            )
        ).one()
        return D(row[0]), int(row[1])

    async def _payment_total_before(self, party_id: str, direction: str, before: date) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount + Payment.discount_given), 0)).where(
                    Payment.business_id == self.business_id,
                    Payment.party_id == party_id,
                    Payment.direction == direction,
                    Payment.is_deleted.is_(False),
                    Payment.payment_date < before,
                )
            )
        ).scalar_one()
        return D(value)


class PartyGroupService(BaseService[PartyGroup]):
    model = PartyGroup
    entity_name = "party_group"

    async def create(self, data: dict[str, Any]) -> PartyGroup:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        group = PartyGroup(business_id=self.business_id, **{k: v for k, v in data.items() if hasattr(PartyGroup, k)})
        stamp_sync(group, self.actor, client_uuid=client_uuid)
        self.db.add(group)
        await self.db.flush()
        await self.track("create", group, label=group.name)
        return group

    async def list_with_counts(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(PartyGroup, func.count(Party.id))
                .outerjoin(
                    Party,
                    (Party.group_id == PartyGroup.id) & (Party.is_deleted.is_(False)),
                )
                .where(PartyGroup.business_id == self.business_id, PartyGroup.is_deleted.is_(False))
                .group_by(PartyGroup.id)
                .order_by(PartyGroup.name)
            )
        ).all()
        return [{"group": g, "party_count": int(c)} for g, c in rows]


def _voucher_label(v: Voucher) -> str:
    labels = {
        VoucherType.SALE: "Sale invoice",
        VoucherType.PURCHASE: "Purchase bill",
        VoucherType.SALE_RETURN: "Sale return (credit note)",
        VoucherType.PURCHASE_RETURN: "Purchase return (debit note)",
    }
    return f"{labels.get(v.voucher_type, v.voucher_type)} {v.number}"
