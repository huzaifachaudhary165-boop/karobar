"""Own-account transfers, cheque tracking and loans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.loan_maths import Instalment, add_months, emi, schedule, split_payment
from app.core.money import ZERO, money
from app.models.enums import (
    ChequeStatus, InterestType, LoanStatus, PaymentDirection, PaymentMode,
)
from app.models.finance import AccountTransfer, Loan, LoanPayment
from app.models.payment import Account, Payment
from app.services.base import BaseService, stamp_sync

# Cheques that have not yet settled one way or the other.
_OPEN_CHEQUES = (ChequeStatus.PENDING, ChequeStatus.DEPOSITED)


class TransferService(BaseService[AccountTransfer]):
    """Cash banked, money withdrawn, a wallet topped up from the bank."""

    model = AccountTransfer
    entity_name = "account_transfer"

    async def create(self, data: dict[str, Any]) -> AccountTransfer:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        if client_uuid and (existing := await self.get_by_client_uuid(client_uuid)):
            return existing

        source_id, target_id = data["from_account_id"], data["to_account_id"]
        if source_id == target_id:
            raise BusinessRuleError("Pick two different accounts to transfer between.")

        amount = money(data.get("amount") or ZERO)
        if amount <= 0:
            raise BusinessRuleError("Transfer amount must be more than zero.")
        charges = money(data.get("charges") or ZERO)
        if charges < 0:
            raise BusinessRuleError("Bank charges cannot be negative.")

        source, target = await self._account_pair(source_id, target_id)

        row = AccountTransfer(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            transfer_date=data.get("transfer_date") or date.today(),
            amount=amount,
            charges=charges,
            **{
                k: v for k, v in data.items()
                if hasattr(AccountTransfer, k)
                and k not in {"amount", "charges", "transfer_date"}
            },
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()

        # The fee leaves the sending account and arrives nowhere: that is what
        # makes a transfer with charges the one case where the two sides differ.
        source.balance = money(source.balance - amount - charges)
        target.balance = money(target.balance + amount)

        await self.track("create", row, label=f"{source.name} → {target.name}")
        return row

    async def delete(self, transfer_id: str) -> None:
        row = await self.get_or_404(transfer_id)
        source, target = await self._account_pair(row.from_account_id, row.to_account_id)
        source.balance = money(source.balance + row.amount + row.charges)
        target.balance = money(target.balance - row.amount)
        await self.soft_delete(row, label=f"{source.name} → {target.name}")

    async def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        account_id: str | None = None,
        limit: int = 100,
    ) -> list[tuple[AccountTransfer, Account, Account]]:
        source = aliased(Account, name="source_account")
        target = aliased(Account, name="target_account")
        stmt = (
            select(AccountTransfer, source, target)
            .join(source, source.id == AccountTransfer.from_account_id)
            .join(target, target.id == AccountTransfer.to_account_id)
            .where(
                AccountTransfer.business_id == self.business_id,
                AccountTransfer.is_deleted.is_(False),
            )
        )
        if start:
            stmt = stmt.where(AccountTransfer.transfer_date >= start)
        if end:
            stmt = stmt.where(AccountTransfer.transfer_date <= end)
        if account_id:
            stmt = stmt.where(
                or_(
                    AccountTransfer.from_account_id == account_id,
                    AccountTransfer.to_account_id == account_id,
                )
            )
        rows = (
            await self.db.execute(stmt.order_by(AccountTransfer.transfer_date.desc()).limit(limit))
        ).all()
        return [(r[0], r[1], r[2]) for r in rows]

    async def _account_pair(self, source_id: str, target_id: str) -> tuple[Account, Account]:
        rows = {
            a.id: a
            for a in (
                await self.db.execute(
                    select(Account).where(
                        Account.business_id == self.business_id,
                        Account.is_deleted.is_(False),
                        Account.id.in_([source_id, target_id]),
                    )
                )
            ).scalars().all()
        }
        missing = [i for i in (source_id, target_id) if i not in rows]
        if missing:
            raise NotFoundError("Account not found.", details={"id": missing[0]})
        return rows[source_id], rows[target_id]


class ChequeService:
    """Cheques written and received, and what became of them.

    A cheque is a promise, not money. It only counts as paid once the bank says
    so, which is why the balance moves on clearing rather than on writing —
    otherwise a bounced cheque leaves a shop believing it has money it never got.
    """

    def __init__(self, db, actor) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def list(
        self,
        *,
        status: str | None = None,
        direction: str | None = None,
        due_before: date | None = None,
        limit: int = 200,
    ) -> list[Payment]:
        stmt = select(Payment).where(
            Payment.business_id == self.business_id,
            Payment.is_deleted.is_(False),
            Payment.mode == PaymentMode.CHEQUE,
        )
        if status:
            stmt = stmt.where(Payment.cheque_status == status)
        else:
            stmt = stmt.where(Payment.cheque_status.in_(list(_OPEN_CHEQUES)))
        if direction:
            stmt = stmt.where(Payment.direction == direction)
        if due_before:
            stmt = stmt.where(Payment.cheque_date <= due_before)

        stmt = stmt.order_by(
            Payment.cheque_date.is_(None), Payment.cheque_date.asc(), Payment.payment_date.desc()
        ).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def summary(self) -> dict[str, Any]:
        rows = await self.list(limit=1000)
        today = date.today()
        incoming = [p for p in rows if p.direction == PaymentDirection.IN]
        outgoing = [p for p in rows if p.direction == PaymentDirection.OUT]
        return {
            "to_deposit_count": len(incoming),
            "to_deposit_amount": money(sum((p.amount for p in incoming), ZERO)),
            "to_clear_count": len(outgoing),
            "to_clear_amount": money(sum((p.amount for p in outgoing), ZERO)),
            "overdue_count": len([p for p in rows if p.cheque_date and p.cheque_date < today]),
        }

    async def set_status(
        self, payment_id: str, new_status: str, *, note: str | None = None
    ) -> Payment:
        payment = (
            await self.db.execute(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            raise NotFoundError("Payment not found.", details={"id": payment_id})
        if payment.mode != PaymentMode.CHEQUE:
            raise BusinessRuleError("That payment was not made by cheque.")

        was_settled = payment.cheque_status == ChequeStatus.CLEARED
        now_settled = new_status == ChequeStatus.CLEARED

        if was_settled and new_status == ChequeStatus.PENDING:
            raise BusinessRuleError(
                "A cleared cheque cannot go back to pending. "
                "Mark it bounced if the bank returned it."
            )

        payment.cheque_status = new_status
        if note:
            payment.notes = f"{payment.notes}\n{note}".strip() if payment.notes else note

        # The account only moves when the cheque actually settles, and moves
        # back if the bank later returns it.
        if now_settled and not was_settled:
            await self._move_balance(payment, payment.signed_amount)
        elif was_settled and not now_settled:
            await self._move_balance(payment, -payment.signed_amount)

        payment.bump_revision()
        return payment

    async def _move_balance(self, payment: Payment, delta: Decimal) -> None:
        if not payment.account_id:
            return
        account = (
            await self.db.execute(
                select(Account).where(
                    Account.id == payment.account_id, Account.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        if account:
            account.balance = money(account.balance + delta)


class LoanService(BaseService[Loan]):
    """Borrowings and their repayment."""

    model = Loan
    entity_name = "loan"

    async def create(self, data: dict[str, Any]) -> Loan:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        if client_uuid and (existing := await self.get_by_client_uuid(client_uuid)):
            return existing

        principal = money(data.get("principal") or ZERO)
        if principal <= 0:
            raise BusinessRuleError("Loan amount must be more than zero.")

        tenure = int(data.get("tenure_months") or 0)
        rate = money(data.get("interest_rate") or ZERO)
        interest_type = data.get("interest_type") or InterestType.REDUCING
        if rate <= 0:
            interest_type = InterestType.NONE

        instalment = money(data.get("emi_amount") or ZERO)
        if instalment <= 0 and tenure > 0:
            instalment = emi(principal, rate, tenure, interest_type)

        start = data.get("start_date") or date.today()
        row = Loan(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            principal=principal,
            outstanding_principal=principal,
            interest_rate=rate,
            interest_type=interest_type,
            tenure_months=tenure,
            emi_amount=instalment,
            start_date=start,
            first_due_date=data.get("first_due_date") or (add_months(start, 1) if tenure else None),
            status=LoanStatus.ACTIVE,
            **{
                k: v for k, v in data.items()
                if hasattr(Loan, k) and k not in {
                    "principal", "interest_rate", "interest_type", "tenure_months",
                    "emi_amount", "start_date", "first_due_date", "status",
                }
            },
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()

        # Borrowed money is money in hand — the account it landed in has to show it.
        if row.account_id:
            await self._move_balance(row.account_id, principal)

        await self.track("create", row, label=row.lender_name)
        return row

    async def update(self, loan_id: str, data: dict[str, Any]) -> Loan:
        row = await self.get_or_404(loan_id)
        # These are settled by what has actually been repaid, not by an edit.
        for owned in ("outstanding_principal", "principal_paid", "interest_paid", "status"):
            data.pop(owned, None)

        changes = self.apply_fields(row, data)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.lender_name)
        return row

    async def delete(self, loan_id: str) -> None:
        row = await self.get_or_404(loan_id)
        if row.instalments_paid:
            raise BusinessRuleError(
                f"{row.instalments_paid} repayment(s) are recorded against this loan. "
                "Delete those first."
            )
        if row.account_id:
            await self._move_balance(row.account_id, -row.principal)
        await self.soft_delete(row, label=row.lender_name)

    async def list(self, *, status: str | None = None) -> list[Loan]:
        stmt = self.base_query()
        if status:
            stmt = stmt.where(Loan.status == status)
        return list(
            (await self.db.execute(stmt.order_by(Loan.status, Loan.start_date.desc())))
            .scalars().all()
        )

    async def summary(self) -> dict[str, Any]:
        rows = await self.list()
        active = [loan for loan in rows if loan.status == LoanStatus.ACTIVE]
        return {
            "active_count": len(active),
            "total_borrowed": money(sum((loan.principal for loan in rows), ZERO)),
            "total_outstanding": money(sum((loan.outstanding_principal for loan in active), ZERO)),
            "monthly_commitment": money(sum((loan.emi_amount for loan in active), ZERO)),
            "interest_paid": money(sum((loan.interest_paid for loan in rows), ZERO)),
        }

    async def schedule_for(self, loan_id: str) -> list[Instalment]:
        loan = await self.get_or_404(loan_id)
        return schedule(
            loan.principal,
            loan.interest_rate,
            loan.tenure_months,
            loan.start_date,
            loan.interest_type,
            instalment=loan.emi_amount or None,
        )

    async def record_payment(self, loan_id: str, data: dict[str, Any]) -> LoanPayment:
        loan = await self.get_or_404(loan_id)
        if loan.status == LoanStatus.CLOSED:
            raise BusinessRuleError("This loan is already settled.")

        amount = money(data.get("amount") or ZERO)
        if amount <= 0:
            raise BusinessRuleError("Repayment amount must be more than zero.")

        flat_interest = None
        if loan.interest_type == InterestType.FLAT and loan.tenure_months:
            total_interest = money(
                loan.principal * loan.interest_rate / Decimal("100")
                * Decimal(loan.tenure_months) / Decimal("12")
            )
            flat_interest = money(total_interest / loan.tenure_months)

        principal_part, interest_part = split_payment(
            loan.outstanding_principal,
            amount,
            loan.interest_rate,
            loan.interest_type,
            flat_monthly_interest=flat_interest,
        )

        # A payment beyond what is owed is a mistake worth naming, not silently
        # absorbing — an overpaid loan hides a keying error nobody looks for.
        if principal_part + interest_part < amount:
            raise BusinessRuleError(
                f"Only {money(principal_part + interest_part)} is owed on this loan, "
                f"but {amount} was entered.",
                details={"owed": str(loan.outstanding_principal)},
            )

        loan.outstanding_principal = money(loan.outstanding_principal - principal_part)
        loan.principal_paid = money(loan.principal_paid + principal_part)
        loan.interest_paid = money(loan.interest_paid + interest_part)

        row = LoanPayment(
            business_id=self.business_id,
            loan_id=loan.id,
            payment_date=data.get("payment_date") or date.today(),
            amount=amount,
            principal_component=principal_part,
            interest_component=interest_part,
            balance_after=loan.outstanding_principal,
            instalment_number=loan.instalments_paid + 1,  # before the count moves
            account_id=data.get("account_id"),
            reference_number=data.get("reference_number"),
            notes=data.get("notes"),
        )
        stamp_sync(row, self.actor)
        self.db.add(row)
        await self.db.flush()
        loan.instalments_paid += 1

        if row.account_id:
            await self._move_balance(row.account_id, -amount)

        if loan.is_settled:
            loan.status = LoanStatus.CLOSED
            loan.closed_on = row.payment_date
        loan.bump_revision()

        await self.record_audit(
            "create", row.id, label=f"{loan.lender_name} instalment",
            entity_type="loan_payment",
            meta={"principal": str(principal_part), "interest": str(interest_part)},
        )
        return row

    async def delete_payment(self, loan_id: str, payment_id: str) -> None:
        loan = await self.get_or_404(loan_id)
        row = (
            await self.db.execute(
                select(LoanPayment).where(
                    LoanPayment.id == payment_id,
                    LoanPayment.loan_id == loan_id,
                    LoanPayment.business_id == self.business_id,
                    LoanPayment.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Repayment not found.", details={"id": payment_id})

        loan.outstanding_principal = money(loan.outstanding_principal + row.principal_component)
        loan.principal_paid = money(loan.principal_paid - row.principal_component)
        loan.interest_paid = money(loan.interest_paid - row.interest_component)
        loan.instalments_paid = max(0, loan.instalments_paid - 1)
        if loan.status == LoanStatus.CLOSED and not loan.is_settled:
            loan.status = LoanStatus.ACTIVE
            loan.closed_on = None
        loan.bump_revision()

        if row.account_id:
            await self._move_balance(row.account_id, row.amount)

        row.soft_delete(self.actor.user_id)
        await self.record_audit(
            "delete", row.id, label=f"{loan.lender_name} instalment", entity_type="loan_payment"
        )

    async def payments_for(self, loan_id: str) -> list[LoanPayment]:
        await self.get_or_404(loan_id)
        return list(
            (
                await self.db.execute(
                    select(LoanPayment)
                    .where(
                        LoanPayment.business_id == self.business_id,
                        LoanPayment.loan_id == loan_id,
                        LoanPayment.is_deleted.is_(False),
                    )
                    .order_by(LoanPayment.payment_date.desc())
                )
            ).scalars().all()
        )

    async def due_soon(self, *, within_days: int = 7) -> list[Loan]:
        """Instalments coming up, so the app can say so before the bank does."""
        rows = await self.list(status=LoanStatus.ACTIVE)
        cutoff = date.today().toordinal() + within_days
        due: list[Loan] = []
        for loan in rows:
            if not loan.tenure_months or not loan.first_due_date:
                continue
            nxt = add_months(loan.first_due_date, loan.instalments_paid)
            if nxt.toordinal() <= cutoff:
                due.append(loan)
        return due

    async def _move_balance(self, account_id: str, delta: Decimal) -> None:
        account = (
            await self.db.execute(
                select(Account).where(
                    Account.id == account_id, Account.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        if account:
            account.balance = money(account.balance + delta)
