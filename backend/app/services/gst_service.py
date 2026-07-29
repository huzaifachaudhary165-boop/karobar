"""GSTR-1 export.

**What this does and does not do.** It produces the GSTR-1 return in the JSON
shape the GST portal's offline utility accepts, plus a CSV for anyone who would
rather look at it in a spreadsheet. You download it and upload it yourself.

It does **not** file the return. Filing means calling the GSTN API, and that
requires being (or paying) a licensed GSP — there is no free path to it, and any
app claiming otherwise is either using a GSP under the covers or not really
filing. Getting the data out correctly is the part that can honestly be free,
and it is also the part that takes the work.

Reference: GSTR-1 offline utility schema, sections B2B / B2CL / B2CS / HSN.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO, D, money
from app.models.business import Business
from app.models.enums import VoucherStatus, VoucherType
from app.models.party import Party
from app.models.voucher import Voucher, VoucherLine
from app.services.base import ActorContext

# A B2C interstate invoice counts as "large" — and so gets itemised in B2CL
# rather than summarised in B2CS — above this value.
B2CL_THRESHOLD = Decimal("250000")

_POSTED = [VoucherStatus.CANCELLED, VoucherStatus.DRAFT]


class GstService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def gstr1(self, start: date, end: date) -> dict[str, Any]:
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()

        rows = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .order_by(Voucher.voucher_date, Voucher.number)
            )
        ).scalars().all()

        parties = {
            p.id: p
            for p in (
                await self.db.execute(
                    select(Party).where(Party.business_id == self.business_id)
                )
            ).scalars().all()
        }

        b2b: dict[str, list[dict[str, Any]]] = {}
        b2cl: dict[str, list[dict[str, Any]]] = {}
        b2cs: dict[tuple[str, Decimal], dict[str, Any]] = {}
        hsn: dict[tuple[str, Decimal], dict[str, Any]] = {}
        skipped: list[dict[str, str]] = []

        home_state = (business.state_code or "").strip()

        for voucher in rows:
            party = parties.get(voucher.party_id) if voucher.party_id else None
            gstin = (getattr(party, "gstin", None) or "").strip().upper()
            place = (getattr(party, "state_code", None) or home_state or "").strip()
            interstate = bool(place and home_state and place != home_state)

            lines = list(voucher.lines)
            for line in lines:
                self._add_hsn(hsn, line, interstate)

            if gstin:
                # Registered buyer → B2B, itemised, one entry per invoice.
                b2b.setdefault(gstin, []).append(
                    self._invoice_block(voucher, place, interstate)
                )
            elif interstate and D(voucher.total) > B2CL_THRESHOLD:
                b2cl.setdefault(place, []).append(
                    self._invoice_block(voucher, place, interstate)
                )
            else:
                # Everything else is summarised by rate and place of supply.
                for line in lines:
                    rate = D(line.tax_rate or 0)
                    key = (place, rate)
                    entry = b2cs.setdefault(
                        key,
                        {
                            "sply_ty": "INTER" if interstate else "INTRA",
                            "pos": place,
                            "typ": "OE",
                            "rt": float(rate),
                            "txval": ZERO,
                            "iamt": ZERO,
                            "camt": ZERO,
                            "samt": ZERO,
                        },
                    )
                    self._accumulate(entry, line, interstate)

            if not place:
                skipped.append(
                    {
                        "invoice": voucher.number,
                        "reason": "No state code on the customer — place of supply is unknown.",
                    }
                )

        return {
            "gstin": (business.gstin or "").strip().upper(),
            "fp": f"{end.month:02d}{end.year}",   # the portal's period format: MMYYYY
            "from": start.isoformat(),
            "to": end.isoformat(),
            "b2b": [
                {"ctin": gstin, "inv": invoices} for gstin, invoices in sorted(b2b.items())
            ],
            "b2cl": [
                {"pos": pos, "inv": invoices} for pos, invoices in sorted(b2cl.items())
            ],
            "b2cs": [self._money_out(e) for e in b2cs.values()],
            "hsn": {"data": [self._money_out(e) for e in hsn.values()]},
            # Surfaced rather than silently dropped: an invoice missing a state
            # code files under the wrong place of supply, which is a real problem
            # the shopkeeper can fix in two minutes if they are told.
            "needs_attention": skipped,
        }

    def _invoice_block(
        self, voucher: Voucher, place: str, interstate: bool
    ) -> dict[str, Any]:
        items = []
        for index, line in enumerate(voucher.lines, start=1):
            rate = D(line.tax_rate or 0)
            taxable = money(D(line.taxable_amount or line.total or 0))
            tax = money(taxable * rate / 100)
            detail: dict[str, Any] = {"rt": float(rate), "txval": float(taxable)}
            if interstate:
                detail["iamt"] = float(tax)
            else:
                half = money(tax / 2)
                detail["camt"] = float(half)
                detail["samt"] = float(tax - half)
            items.append({"num": index, "itm_det": detail})

        return {
            "inum": voucher.number,
            "idt": voucher.voucher_date.strftime("%d-%m-%Y"),
            "val": float(money(D(voucher.total))),
            "pos": place,
            "rchrg": "N",
            "inv_typ": "R",
            "itms": items,
        }

    def _accumulate(self, entry: dict[str, Any], line: VoucherLine, interstate: bool) -> None:
        rate = D(line.tax_rate or 0)
        taxable = money(D(line.taxable_amount or line.total or 0))
        tax = money(taxable * rate / 100)

        entry["txval"] = money(entry["txval"] + taxable)
        if interstate:
            entry["iamt"] = money(entry["iamt"] + tax)
        else:
            half = money(tax / 2)
            entry["camt"] = money(entry["camt"] + half)
            entry["samt"] = money(entry["samt"] + (tax - half))

    def _add_hsn(
        self, hsn: dict[tuple[str, Decimal], dict[str, Any]], line: VoucherLine, interstate: bool
    ) -> None:
        code = (line.hsn_code or "").strip() or "NA"
        rate = D(line.tax_rate or 0)
        entry = hsn.setdefault(
            (code, rate),
            {
                "hsn_sc": code,
                "desc": line.item_name[:30],
                "uqc": (line.unit_label or "NOS").upper()[:3],
                "qty": ZERO,
                "rt": float(rate),
                "txval": ZERO,
                "iamt": ZERO,
                "camt": ZERO,
                "samt": ZERO,
            },
        )
        entry["qty"] = D(entry["qty"]) + D(line.qty or 0)
        self._accumulate(entry, line, interstate)

    @staticmethod
    def _money_out(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in entry.items()
        }

    # ── spreadsheet view ─────────────────────────────────────────
    @staticmethod
    def to_csv(report: dict[str, Any]) -> str:
        """A flat view of the same numbers, for an accountant who works in Excel."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["Section", "GSTIN / Place", "Invoice", "Date", "Taxable", "Rate %",
             "IGST", "CGST", "SGST", "Invoice total"]
        )

        for block in report.get("b2b", []):
            for inv in block["inv"]:
                for item in inv["itms"]:
                    d = item["itm_det"]
                    writer.writerow([
                        "B2B", block["ctin"], inv["inum"], inv["idt"],
                        d.get("txval", 0), d.get("rt", 0),
                        d.get("iamt", 0), d.get("camt", 0), d.get("samt", 0), inv["val"],
                    ])

        for block in report.get("b2cl", []):
            for inv in block["inv"]:
                for item in inv["itms"]:
                    d = item["itm_det"]
                    writer.writerow([
                        "B2CL", block["pos"], inv["inum"], inv["idt"],
                        d.get("txval", 0), d.get("rt", 0),
                        d.get("iamt", 0), d.get("camt", 0), d.get("samt", 0), inv["val"],
                    ])

        for entry in report.get("b2cs", []):
            writer.writerow([
                "B2CS", entry.get("pos", ""), "", "",
                entry.get("txval", 0), entry.get("rt", 0),
                entry.get("iamt", 0), entry.get("camt", 0), entry.get("samt", 0), "",
            ])

        return buffer.getvalue()
