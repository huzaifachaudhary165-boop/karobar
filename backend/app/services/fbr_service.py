"""The Pakistani sales tax return, and the sales register that goes with it.

**What this does and does not do.** It produces Annexure C — the sales register
the monthly return is built from — as CSV, and the summary a shop needs to fill
the return in. You download it and file it yourself on IRIS.

It does not file the return. Filing means an authenticated session on the FBR's
portal, and no app can honestly do that on a shop's behalf without holding
their credentials. Getting the figures right is the part that can be free, and
it is also the part that takes the work.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.money import ZERO, money
from app.core.pakistan_tax import TaxSetup, authority_for, net_payable
from app.models.business import Business, BusinessSettings
from app.models.enums import VoucherStatus, VoucherType
from app.models.party import Party
from app.models.voucher import Voucher
from app.services.base import ActorContext

_NOT_POSTED = [VoucherStatus.CANCELLED, VoucherStatus.DRAFT, VoucherStatus.CONVERTED]

# Annexure C's own column names, so the file can be pasted straight into the
# portal's template rather than re-typed.
ANNEXURE_C_COLUMNS = [
    "Buyer NTN/CNIC",
    "Buyer STRN",
    "Buyer Name",
    "Buyer Type",
    "Document Type",
    "Document Number",
    "Document Date",
    "HS Code",
    "Sale Type",
    "Rate",
    "Value of Sales Excluding Sales Tax",
    "Sales Tax",
    "Further Tax",
    "Extra Tax",
    "Total Value of Sales",
]


class FbrService:
    def __init__(self, db, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def setup(self) -> TaxSetup:
        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(
                    BusinessSettings.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        if cfg is None:
            return TaxSetup()
        return TaxSetup(
            enabled=cfg.fbr_enabled,
            rate=cfg.sales_tax_rate,
            further_tax_enabled=cfg.further_tax_enabled,
            further_tax_rate=cfg.further_tax_rate,
            withholding_enabled=cfg.withholding_enabled,
            withholding_rate=cfg.withholding_rate,
            prices_include_tax=cfg.prices_include_tax,
        )

    async def annexure_c(self, start: date, end: date) -> list[dict[str, Any]]:
        """Every sale in the period, one row per invoice.

        Buyer type is what decides further tax, so it is stated on every row
        rather than left for whoever reads the file to work out.
        """
        rows = (
            await self.db.execute(
                select(Voucher, Party)
                .outerjoin(Party, Party.id == Voucher.party_id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type.in_([VoucherType.SALE, VoucherType.SALE_RETURN]),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .order_by(Voucher.voucher_date, Voucher.number)
            )
        ).all()

        out: list[dict[str, Any]] = []
        for voucher, party in rows:
            registered = bool(party and party.strn and party.strn.strip())
            is_return = voucher.voucher_type == VoucherType.SALE_RETURN
            sign = Decimal("-1") if is_return else Decimal("1")

            out.append(
                {
                    "Buyer NTN/CNIC": (party.ntn if party else "") or "",
                    "Buyer STRN": (party.strn if party else "") or "",
                    "Buyer Name": voucher.party_name or "Walk-in",
                    "Buyer Type": "Registered" if registered else "Unregistered",
                    "Document Type": "Credit Note" if is_return else "Sale Invoice",
                    "Document Number": voucher.number,
                    "Document Date": voucher.voucher_date.isoformat(),
                    "HS Code": _first_hs_code(voucher),
                    "Sale Type": "Goods at standard rate",
                    "Rate": str(_effective_rate(voucher)),
                    "Value of Sales Excluding Sales Tax": str(
                        money(voucher.taxable_amount * sign)
                    ),
                    "Sales Tax": str(money(voucher.tax_amount * sign)),
                    # Held on the voucher when it was raised rather than
                    # recomputed here: the rate may have changed since, and the
                    # return has to say what was actually charged.
                    "Further Tax": str(money(_further_of(voucher) * sign)),
                    "Extra Tax": "0",
                    "Total Value of Sales": str(money(voucher.total * sign)),
                }
            )
        return out

    async def annexure_c_csv(self, start: date, end: date) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=ANNEXURE_C_COLUMNS)
        writer.writeheader()
        for row in await self.annexure_c(start, end):
            writer.writerow(row)
        return buffer.getvalue()

    async def monthly_return(self, start: date, end: date) -> dict[str, Any]:
        """The figures the return is filled in from.

        Purchases are counted as input tax only where the supplier is
        registered: tax paid to an unregistered supplier is not reclaimable,
        and counting it would overstate the credit and understate what is owed.
        """
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        setup = await self.setup()

        sales = (
            await self.db.execute(
                select(Voucher, Party)
                .outerjoin(Party, Party.id == Voucher.party_id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type.in_([VoucherType.SALE, VoucherType.SALE_RETURN]),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).all()

        purchases = (
            await self.db.execute(
                select(Voucher, Party)
                .outerjoin(Party, Party.id == Voucher.party_id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type.in_(
                        [VoucherType.PURCHASE, VoucherType.PURCHASE_RETURN]
                    ),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).all()

        registered_sales = unregistered_sales = ZERO
        output_tax = further_tax = ZERO
        for voucher, party in sales:
            sign = Decimal("-1") if voucher.voucher_type == VoucherType.SALE_RETURN else Decimal("1")
            value = voucher.taxable_amount * sign
            if party and party.strn:
                registered_sales += value
            else:
                unregistered_sales += value
            output_tax += voucher.tax_amount * sign
            further_tax += _further_of(voucher) * sign

        input_tax = unclaimable = ZERO
        for voucher, party in purchases:
            sign = (
                Decimal("-1")
                if voucher.voucher_type == VoucherType.PURCHASE_RETURN
                else Decimal("1")
            )
            claimable = bool(party and party.strn and party.strn.strip())
            if claimable:
                input_tax += voucher.tax_amount * sign
            else:
                unclaimable += voucher.tax_amount * sign

        payable, carried = net_payable(money(output_tax + further_tax), money(input_tax))

        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(
                    BusinessSettings.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        authority = authority_for(
            (cfg.province if cfg else None) or business.state
        )

        return {
            "enabled": setup.enabled,
            "period_start": start,
            "period_end": end,
            "ntn": business.ntn,
            "strn": business.strn,
            "registered_sales": money(registered_sales),
            "unregistered_sales": money(unregistered_sales),
            "total_sales": money(registered_sales + unregistered_sales),
            "output_tax": money(output_tax),
            "further_tax": money(further_tax),
            "input_tax": money(input_tax),
            # Stated rather than hidden: a shop buying from unregistered
            # suppliers is losing this every month and has a reason to change.
            "unclaimable_input_tax": money(unclaimable),
            "net_payable": payable,
            "carried_forward": carried,
            "sale_count": len(sales),
            "purchase_count": len(purchases),
            "provincial_authority": authority[1] if authority else None,
        }


def _further_of(voucher: Voucher) -> Decimal:
    """Further tax as it was charged, not as it would be charged today."""
    return voucher.further_tax_amount or ZERO


def _effective_rate(voucher: Voucher) -> Decimal:
    if voucher.taxable_amount and voucher.taxable_amount > 0:
        return money(voucher.tax_amount / voucher.taxable_amount * Decimal("100"))
    return ZERO


def _first_hs_code(voucher: Voucher) -> str:
    for line in voucher.lines:
        if line.hsn_code:
            return line.hsn_code
    return ""
