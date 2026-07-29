"""Tax computation — GST (India), Sales Tax (Pakistan) and plain VAT.

The core rule: a supply is *interstate* when the supplier's state code differs
from the place of supply. Interstate → IGST; intrastate → CGST + SGST (half each).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.core.money import D, inclusive_split, money, pct

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$")
NTN_RE = re.compile(r"^\d{7}-?\d?$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")

GST_SLABS = [Decimal(s) for s in ("0", "0.25", "3", "5", "12", "18", "28")]
PK_SALES_TAX_SLABS = [Decimal(s) for s in ("0", "1", "5", "10", "16", "17", "18")]


@dataclass(slots=True)
class TaxBreakdown:
    taxable: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    cess: Decimal = Decimal("0")

    @property
    def total_tax(self) -> Decimal:
        return money(self.cgst + self.sgst + self.igst + self.cess)

    @property
    def total(self) -> Decimal:
        return money(self.taxable + self.total_tax)

    def __add__(self, other: "TaxBreakdown") -> "TaxBreakdown":
        return TaxBreakdown(
            taxable=self.taxable + other.taxable,
            cgst=self.cgst + other.cgst,
            sgst=self.sgst + other.sgst,
            igst=self.igst + other.igst,
            cess=self.cess + other.cess,
        )

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "taxable": money(self.taxable),
            "cgst": money(self.cgst),
            "sgst": money(self.sgst),
            "igst": money(self.igst),
            "cess": money(self.cess),
            "tax_amount": self.total_tax,
            "total": self.total,
        }


def is_interstate(supplier_state_code: str | None, place_of_supply: str | None) -> bool:
    if not supplier_state_code or not place_of_supply:
        return False
    return supplier_state_code.strip().lstrip("0") != place_of_supply.strip().lstrip("0")


def compute_line_tax(
    gross: Decimal | float | str,
    rate: Decimal | float | str,
    *,
    interstate: bool = False,
    inclusive: bool = False,
    cess_rate: Decimal | float | str = 0,
) -> TaxBreakdown:
    """`gross` is the post-discount line amount."""
    rate_d, cess_d = D(rate), D(cess_rate)
    combined = rate_d + cess_d

    if inclusive:
        taxable, _ = inclusive_split(gross, combined)
    else:
        taxable = money(gross)

    cess = pct(taxable, cess_d) if cess_d else Decimal("0")
    if interstate:
        return TaxBreakdown(taxable=taxable, igst=pct(taxable, rate_d), cess=cess)
    half = rate_d / 2
    return TaxBreakdown(taxable=taxable, cgst=pct(taxable, half), sgst=pct(taxable, half), cess=cess)


def gstin_state_code(gstin: str | None) -> str | None:
    return gstin.strip()[:2] if gstin and len(gstin.strip()) >= 2 else None


def validate_gstin(gstin: str | None) -> tuple[bool, str | None]:
    if not gstin:
        return True, None
    value = gstin.strip().upper()
    if not GSTIN_RE.match(value):
        return False, "GSTIN must be 15 characters, e.g. 27AAPFU0939F1ZV."
    if not _gstin_checksum_ok(value):
        return False, "GSTIN checksum is invalid."
    return True, None


def _gstin_checksum_ok(gstin: str) -> bool:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(gstin[:14]):
        idx = alphabet.find(ch)
        if idx < 0:
            return False
        product = idx * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return alphabet[(36 - total % 36) % 36] == gstin[14]


def validate_ntn(ntn: str | None) -> tuple[bool, str | None]:
    if not ntn:
        return True, None
    return (True, None) if NTN_RE.match(ntn.strip()) else (False, "NTN must be 7 or 8 digits.")


def validate_tax_number(number: str | None, country: str) -> tuple[bool, str | None]:
    if country.lower() in {"india", "in"}:
        return validate_gstin(number)
    if country.lower() in {"pakistan", "pk"}:
        return validate_ntn(number)
    return True, None


def nearest_slab(rate: Decimal | float | str, country: str = "Pakistan") -> Decimal:
    """Snap a free-typed rate to the closest legal slab — helps the AI stay valid."""
    slabs = GST_SLABS if country.lower() in {"india", "in"} else PK_SALES_TAX_SLABS
    r = D(rate)
    return min(slabs, key=lambda s: abs(s - r))


INDIAN_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}

PAKISTAN_PROVINCES: dict[str, str] = {
    "PB": "Punjab", "SD": "Sindh", "KP": "Khyber Pakhtunkhwa", "BL": "Balochistan",
    "IS": "Islamabad Capital Territory", "GB": "Gilgit-Baltistan", "AK": "Azad Kashmir",
}
