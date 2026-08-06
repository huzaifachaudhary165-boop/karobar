"""Money that is neither a sale nor a purchase: own-account transfers and loans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, Money
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import InterestType, LoanStatus, LoanType


class AccountTransfer(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin,
                      AuditedMixin):
    """Moving your own money between your own accounts.

    Cash banked at the end of the day, a withdrawal for the counter float, a
    top-up from bank to easypaisa. This is not income or expenditure — the
    business is no richer afterwards — so it never touches profit, only the two
    account balances.
    """

    __table_args__ = (
        UniqueConstraint("business_id", "client_uuid", name="uq_transfer_client_uuid"),
        Index("ix_transfers_biz_date", "business_id", "transfer_date"),
    )

    from_account_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_account_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Banks charge for demand drafts and online transfers; leaving it out would
    # make the two balances refuse to reconcile with the statement.
    charges: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def total_debited(self) -> Decimal:
        """What actually leaves the source account, fee included."""
        return self.amount + self.charges


class Loan(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    """Borrowed money and what is still owed on it.

    Covers a bank term loan as well as the interest-free borrowing that is far
    more common in a small shop — money from a relative, a committee, a
    supplier's credit line.
    """

    __table_args__ = (
        UniqueConstraint("business_id", "client_uuid", name="uq_loan_client_uuid"),
        Index("ix_loans_biz_status", "business_id", "status"),
    )

    lender_name: Mapped[str] = mapped_column(String(200), nullable=False)
    loan_type: Mapped[str] = mapped_column(String(16), default=LoanType.BANK, nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    principal: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    interest_type: Mapped[str] = mapped_column(
        String(16), default=InterestType.REDUCING, nullable=False
    )
    tenure_months: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emi_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    first_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Where the borrowed money landed, so the account balance reflects it.
    account_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    outstanding_principal: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    principal_paid: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    interest_paid: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    # A stored count rather than len(instalments): reading the collection off a
    # row that was just written triggers a lazy load in the wrong context, and
    # the running totals beside it are kept the same way.
    instalments_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=LoanStatus.ACTIVE, nullable=False)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Loaded only when a caller asks for it. A list of loans has no use for
    # every instalment of every one of them.
    instalments: Mapped[list["LoanPayment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", lazy="noload"
    )

    @property
    def total_paid(self) -> Decimal:
        return self.principal_paid + self.interest_paid

    @property
    def is_settled(self) -> bool:
        return self.outstanding_principal <= 0

    @property
    def instalments_left(self) -> int:
        if not self.tenure_months:
            return 0
        return max(0, self.tenure_months - self.instalments_paid)


class LoanPayment(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """One instalment, split into what repaid the debt and what was rent on it.

    The split matters: only the interest half is a business expense. Treating
    the whole instalment as an expense understates profit by the principal
    every single month.
    """

    __table_args__ = (Index("ix_loan_payments_loan_date", "loan_id", "payment_date"),)

    loan_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    principal_component: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    interest_component: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    balance_after: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    instalment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    account_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    expense_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    loan: Mapped["Loan"] = relationship(back_populates="instalments")
