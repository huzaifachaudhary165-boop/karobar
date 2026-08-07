"""Loyalty points: earning, spending, and letting them go stale."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import BusinessRuleError
from app.core.loyalty import (
    Lot, allocate, expiry_for, max_redeemable, points_for, scheme_cost_percent,
    stale_lots, usable_balance, value_of,
)
from app.core.money import ZERO, money
from app.models.base import utcnow
from app.models.enums import PaymentDirection, PaymentMode
from app.models.loyalty import LoyaltyEntry, LoyaltyProgram
from app.models.party import Party
from app.models.payment import PaymentAllocation
from app.services.base import ActorContext, stamp_sync

EARNED = "earned"
REDEEMED = "redeemed"
EXPIRED = "expired"
ADJUSTED = "adjusted"
REVERSED = "reversed"


class LoyaltyService:
    """Every movement of points goes through here.

    Nothing writes a balance directly. The balance is the sum of the ledger, in
    the same way stock is the sum of the stock ledger — a customer who asks
    where their points went is asking for the list, and a shop that cannot
    produce it will be argued with and lose.
    """

    def __init__(self, db, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    # ── the scheme ─────────────────────────────────────────────────
    async def program(self) -> LoyaltyProgram | None:
        return (
            await self.db.execute(
                select(LoyaltyProgram).where(
                    LoyaltyProgram.business_id == self.business_id,
                    LoyaltyProgram.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def active_program(self) -> LoyaltyProgram | None:
        row = await self.program()
        return row if row and row.is_active else None

    async def save_program(self, data: dict[str, Any]) -> LoyaltyProgram:
        row = await self.program()
        if row is None:
            # Spelled out rather than left to the column defaults: those only
            # land on flush, and the checks below run before that — a
            # half-built row would compare None against a number and blow up
            # with something that says nothing about loyalty schemes.
            row = LoyaltyProgram(
                business_id=self.business_id,
                name="Loyalty points",
                earn_rate=Decimal("0.01"),
                point_value=Decimal("1"),
                min_points_to_redeem=0,
                max_redeem_percent=Decimal("100"),
                is_active=True,
            )
            stamp_sync(row, self.actor)
            self.db.add(row)

        for field, value in data.items():
            if hasattr(LoyaltyProgram, field) and field not in ("id", "business_id"):
                setattr(row, field, value)

        if row.earn_rate < 0 or row.point_value < 0:
            raise BusinessRuleError("A rate cannot be negative.")
        if not 0 <= row.max_redeem_percent <= 100:
            raise BusinessRuleError("The cap on one bill is a percentage, 0 to 100.")

        # A scheme costing more than a fifth of turnover is almost always a
        # typo in one of the two rates, and it would be found in the accounts
        # months later rather than here.
        if scheme_cost_percent(row.earn_rate, row.point_value) > 20:
            raise BusinessRuleError(
                f"That works out at {scheme_cost_percent(row.earn_rate, row.point_value)}% "
                "of every sale. Check the earn rate and what a point is worth."
            )

        await self.db.flush()
        return row

    # ── the balance ────────────────────────────────────────────────
    async def lots_for(self, party_id: str) -> list[Lot]:
        """Every entry still holding points, whatever put them there.

        Not just the earned ones. Points given by hand as goodwill, and points
        handed back when a bill was cancelled, are points the customer has —
        filtering on `earned` made both invisible to the balance while leaving
        them plainly visible in the history the customer is shown.
        """
        rows = (
            await self.db.execute(
                select(LoyaltyEntry).where(
                    LoyaltyEntry.business_id == self.business_id,
                    LoyaltyEntry.party_id == party_id,
                    LoyaltyEntry.remaining > 0,
                )
            )
        ).scalars().all()
        return [Lot(row.id, row.remaining, row.expires_on) for row in rows]

    async def balance(self, party_id: str, on: date | None = None) -> int:
        return usable_balance(await self.lots_for(party_id), on)

    async def history(self, party_id: str, limit: int = 100) -> list[LoyaltyEntry]:
        return list(
            (
                await self.db.execute(
                    select(LoyaltyEntry)
                    .where(
                        LoyaltyEntry.business_id == self.business_id,
                        LoyaltyEntry.party_id == party_id,
                    )
                    .order_by(LoyaltyEntry.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def quote(self, party_id: str, bill_total: Decimal) -> dict[str, Any]:
        """What this customer could take off this bill, and what it is worth."""
        program = await self.active_program()
        if program is None:
            return {"balance": 0, "redeemable": 0, "value": ZERO, "enabled": False}

        balance = await self.balance(party_id)
        redeemable = max_redeemable(
            balance,
            bill_total,
            program.point_value,
            max_percent=program.max_redeem_percent,
            minimum_points=program.min_points_to_redeem,
        )
        return {
            "balance": balance,
            "redeemable": redeemable,
            "value": value_of(redeemable, program.point_value),
            "enabled": True,
            "point_value": program.point_value,
            "min_points": program.min_points_to_redeem,
        }

    # ── movements ──────────────────────────────────────────────────
    async def earn(
        self,
        party_id: str,
        amount: Decimal,
        *,
        voucher_id: str | None = None,
        voucher_number: str | None = None,
        on: date | None = None,
    ) -> LoyaltyEntry | None:
        """Give points for a sale. Silent when there is no scheme running."""
        program = await self.active_program()
        if program is None:
            return None

        earned = points_for(amount, program.earn_rate, program.min_bill_to_earn)
        if earned <= 0:
            return None

        when = on or date.today()
        return await self._post(
            party_id,
            kind=EARNED,
            points=earned,
            remaining=earned,
            expires_on=expiry_for(when, program.expires_after_months),
            voucher_id=voucher_id,
            voucher_number=voucher_number,
        )

    async def redeem(
        self,
        party_id: str,
        points: int,
        *,
        bill_total: Decimal,
        voucher_id: str | None = None,
        voucher_number: str | None = None,
        on: date | None = None,
    ) -> LoyaltyEntry:
        """Spend points against a bill, oldest lot first."""
        program = await self.active_program()
        if program is None:
            raise BusinessRuleError("This shop is not running a points scheme.")
        if points <= 0:
            raise BusinessRuleError("Choose how many points to use.")

        allowed = max_redeemable(
            await self.balance(party_id, on),
            bill_total,
            program.point_value,
            max_percent=program.max_redeem_percent,
            minimum_points=program.min_points_to_redeem,
        )
        if points > allowed:
            raise BusinessRuleError(
                f"At most {allowed} points can be used on this bill.",
                details={"allowed": allowed},
            )

        lots = {lot.id: lot for lot in await self.lots_for(party_id)}
        taken = allocate(list(lots.values()), points, on)

        for lot_id, count in taken:
            row = (
                await self.db.execute(
                    select(LoyaltyEntry).where(LoyaltyEntry.id == lot_id)
                )
            ).scalar_one()
            row.remaining -= count

        # What they were worth today, so a later change to point_value cannot
        # rewrite what the customer was actually given.
        worth = value_of(points, program.point_value)

        entry = await self._post(
            party_id,
            kind=REDEEMED,
            points=-points,
            value=worth,
            voucher_id=voucher_id,
            voucher_number=voucher_number,
        )

        if voucher_id and worth > ZERO:
            await self._settle(party_id, voucher_id, worth, on=on)

        return entry

    async def _settle(
        self, party_id: str, voucher_id: str, worth: Decimal, *, on: date | None
    ) -> None:
        """Record the points as a tender against the bill they were spent on.

        Without this the ledger says the customer spent 200 rupees of points
        and the bill still says they owe 200 rupees. The shopkeeper chases them
        for money the shop itself already took off, and the customer — who
        watched the discount appear on the counter screen — argues, correctly.

        It is a payment rather than a discount because the shop really did earn
        the full amount: the 200 is the cost of the reward scheme, not revenue
        the shop never made. Recording it as a discount would understate sales
        by every reward ever given.
        """
        from app.services.payment_service import PaymentService

        party = (
            await self.db.execute(select(Party).where(Party.id == party_id))
        ).scalar_one_or_none()

        await PaymentService(self.db, self.actor).create_raw(
            direction=PaymentDirection.IN,
            amount=worth,
            party=party,
            mode=PaymentMode.POINTS,
            payment_date=on or date.today(),
            allocations=[{"voucher_id": voucher_id, "amount": worth}],
            notes="Loyalty points",
            source="loyalty",
        )

    async def release_tender(self, voucher_id: str) -> int:
        """Take the points tender back off a bill that is being cancelled.

        The points themselves go back to the customer, so the settlement they
        bought has to come off too — otherwise the shop hands back the points
        and keeps the money they paid for, and the bill reads part-paid by a
        payment nobody can find.

        Cancelling refuses to run while a bill has payments against it, and
        rightly so: a real payment is somebody's actual money and the
        shopkeeper has to decide where it goes. This one is the shop's own
        machinery, not a decision anyone made, so it clears itself.
        """
        from app.models.payment import Payment

        rows = (
            await self.db.execute(
                select(Payment).where(
                    Payment.business_id == self.business_id,
                    Payment.mode == PaymentMode.POINTS,
                    Payment.is_deleted.is_(False),
                    Payment.id.in_(
                        select(PaymentAllocation.payment_id).where(
                            PaymentAllocation.voucher_id == voucher_id
                        )
                    ),
                )
            )
        ).scalars().all()

        if not rows:
            return 0

        from app.services.payment_service import PaymentService

        payments = PaymentService(self.db, self.actor)
        for row in rows:
            await payments.delete(row.id)
        return len(rows)

    async def reverse(self, voucher_id: str) -> int:
        """Undo everything a cancelled bill did to a customer's points.

        Both directions: points it earned come back off, and points it spent go
        back on. A cancelled bill that leaves the customer's points as they
        were is a bill that gave something away for nothing.
        """
        rows = (
            await self.db.execute(
                select(LoyaltyEntry).where(
                    LoyaltyEntry.business_id == self.business_id,
                    LoyaltyEntry.voucher_id == voucher_id,
                    LoyaltyEntry.kind.in_([EARNED, REDEEMED]),
                )
            )
        ).scalars().all()

        undone = 0
        for row in rows:
            if row.kind == EARNED:
                # Only what is still unspent can be taken back. Points already
                # spent on another bill are gone, and clawing them back would
                # make a second customer's bill wrong to fix the first.
                claw = row.remaining
                row.remaining = 0
                if claw <= 0:
                    continue
                await self._post(
                    row.party_id, kind=REVERSED, points=-claw,
                    voucher_id=voucher_id, voucher_number=row.voucher_number,
                    note="Bill cancelled",
                )
            else:
                given_back = abs(row.points)
                await self._post(
                    row.party_id, kind=REVERSED, points=given_back,
                    remaining=given_back, voucher_id=voucher_id,
                    voucher_number=row.voucher_number, note="Bill cancelled",
                )
            undone += 1
        return undone

    async def adjust(self, party_id: str, points: int, note: str) -> LoyaltyEntry:
        """A manual correction, which always has to say why."""
        if points == 0:
            raise BusinessRuleError("An adjustment of zero changes nothing.")
        if not note.strip():
            raise BusinessRuleError("Say why the points are being changed.")

        if points < 0:
            balance = await self.balance(party_id)
            if abs(points) > balance:
                raise BusinessRuleError(
                    f"This customer only has {balance} points."
                )
            lots = {lot.id: lot for lot in await self.lots_for(party_id)}
            for lot_id, count in allocate(list(lots.values()), abs(points)):
                row = (
                    await self.db.execute(
                        select(LoyaltyEntry).where(LoyaltyEntry.id == lot_id)
                    )
                ).scalar_one()
                row.remaining -= count

        return await self._post(
            party_id,
            kind=ADJUSTED,
            points=points,
            remaining=max(0, points),
            note=note.strip(),
        )

    async def expire_stale(self, on: date | None = None) -> dict[str, Any]:
        """Write off points whose date has passed.

        Runs when the app asks, for the same reason the recurring bills do:
        there is no scheduler, so nothing sweeps at midnight. Each write-off is
        its own ledger row, because "your points expired" is a claim a customer
        is entitled to see the date of.
        """
        when = on or date.today()
        rows = (
            await self.db.execute(
                select(LoyaltyEntry).where(
                    LoyaltyEntry.business_id == self.business_id,
                    LoyaltyEntry.remaining > 0,
                    LoyaltyEntry.expires_on.isnot(None),
                    LoyaltyEntry.expires_on < when,
                )
            )
        ).scalars().all()

        by_party: dict[str, int] = {}
        for row in rows:
            by_party[row.party_id] = by_party.get(row.party_id, 0) + row.remaining
            row.remaining = 0
            row.expired_at = utcnow()

        for party_id, points in by_party.items():
            await self._post(
                party_id, kind=EXPIRED, points=-points,
                note=f"Expired on {when.isoformat()}",
            )

        return {
            "customers": len(by_party),
            "points": sum(by_party.values()),
            "checked_on": when,
        }

    async def top_customers(self, limit: int = 20) -> list[tuple[Party, int]]:
        rows = (
            await self.db.execute(
                select(LoyaltyEntry.party_id, func.sum(LoyaltyEntry.remaining))
                .where(
                    LoyaltyEntry.business_id == self.business_id,
                    LoyaltyEntry.remaining > 0,
                )
                .group_by(LoyaltyEntry.party_id)
                .order_by(func.sum(LoyaltyEntry.remaining).desc())
                .limit(limit)
            )
        ).all()
        if not rows:
            return []

        parties = {
            party.id: party
            for party in (
                await self.db.execute(
                    select(Party).where(Party.id.in_([r[0] for r in rows]))
                )
            ).scalars().all()
        }
        return [(parties[pid], int(total)) for pid, total in rows if pid in parties]

    async def _post(
        self,
        party_id: str,
        *,
        kind: str,
        points: int,
        remaining: int = 0,
        value: Decimal = ZERO,
        expires_on: date | None = None,
        voucher_id: str | None = None,
        voucher_number: str | None = None,
        note: str | None = None,
    ) -> LoyaltyEntry:
        row = LoyaltyEntry(
            business_id=self.business_id,
            party_id=party_id,
            kind=kind,
            points=points,
            remaining=remaining,
            value=money(value),
            expires_on=expires_on,
            voucher_id=voucher_id,
            voucher_number=voucher_number,
            note=note,
            created_by=self.actor.user_id,
        )
        stamp_sync(row, self.actor)
        self.db.add(row)
        await self.db.flush()
        # Written after the row exists so the number recorded is the one a
        # customer would have been told at that moment.
        row.balance_after = await self.balance(party_id)
        return row

    @staticmethod
    def describe(program: LoyaltyProgram) -> str:
        return (
            f"{scheme_cost_percent(program.earn_rate, program.point_value)}% "
            "of every sale"
        )

    async def stale_count(self, on: date | None = None) -> int:
        return len(stale_lots(
            [
                Lot(row.id, row.remaining, row.expires_on)
                for row in (
                    await self.db.execute(
                        select(LoyaltyEntry).where(
                            LoyaltyEntry.business_id == self.business_id,
                            LoyaltyEntry.remaining > 0,
                        )
                    )
                ).scalars().all()
            ],
            on,
        ))
