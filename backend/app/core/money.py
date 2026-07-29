"""Decimal money helpers. All arithmetic in the app goes through here."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
CENT = Decimal("0.01")
QTY_Q = Decimal("0.0001")
HUNDRED = Decimal("100")


def D(value: Any, default: Decimal | None = ZERO) -> Decimal:
    """Coerce anything to Decimal without ever going through float."""
    if value is None or value == "":
        if default is None:
            raise ValueError("value is required")
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{value!r} is not a valid number") from exc


def money(value: Any) -> Decimal:
    """Round to 2dp, banker's-rounding-free (HALF_UP is what invoices expect)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def qty(value: Any) -> Decimal:
    return D(value).quantize(QTY_Q, rounding=ROUND_HALF_UP)


def pct(base: Any, percent: Any) -> Decimal:
    """percent% of base, rounded to 2dp."""
    return money(D(base) * D(percent) / HUNDRED)


def inclusive_split(gross: Any, rate: Any) -> tuple[Decimal, Decimal]:
    """Split a tax-inclusive gross amount into (net, tax)."""
    g, r = D(gross), D(rate)
    net = money(g * HUNDRED / (HUNDRED + r)) if r else money(g)
    return net, money(g - net)


def safe_div(a: Any, b: Any, default: Decimal = ZERO) -> Decimal:
    bb = D(b)
    return default if bb == ZERO else D(a) / bb


def growth_pct(current: Any, previous: Any) -> Decimal | None:
    """Percentage change; None when there is no baseline to compare against."""
    prev = D(previous)
    if prev == ZERO:
        return None
    return money((D(current) - prev) / abs(prev) * HUNDRED)


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    return _ONES[n // 100] + " Hundred" + (" " + _under_thousand(n % 100) if n % 100 else "")


def amount_in_words(amount: Any, currency: str = "Rupees", subunit: str = "Paise") -> str:
    """Indian/Pakistani numbering (Lakh/Crore) — printed on every invoice."""
    amt = money(abs(D(amount)))
    whole = int(amt)
    frac = int((amt - whole) * 100)
    if whole == 0:
        words = "Zero"
    else:
        parts: list[str] = []
        for divisor, label in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
            if whole >= divisor:
                parts.append(f"{_under_thousand(whole // divisor)} {label}")
                whole %= divisor
        if whole:
            parts.append(_under_thousand(whole))
        words = " ".join(parts)
    out = f"{currency} {words}"
    if frac:
        out += f" and {_under_thousand(frac)} {subunit}"
    sign = "Minus " if D(amount) < 0 else ""
    return f"{sign}{out} Only"


def format_money(value: Any, symbol: str = "₹", decimals: int = 2) -> str:
    """Indian grouping: 12,34,567.89"""
    v = money(value)
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    whole, _, dec = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    out = f"{symbol}{whole}" + (f".{dec}" if decimals else "")
    return f"-{out}" if neg else out
