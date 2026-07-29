"""Bill scanning: the parts that decide whether a saved bill matches the paper one.

Character recognition happens on the device, so what is tested here is the
server's half — turning rough text into a draft, and not losing money on the way.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.ocr import _apply_document_tax, _sum_lines, _warnings
from app.schemas.voucher import VoucherLineInput


def line(qty: str, rate: str, tax: str | None = None) -> VoucherLineInput:
    return VoucherLineInput(
        item_name="Cement",
        qty=Decimal(qty),
        rate=Decimal(rate),
        tax_rate=Decimal(tax) if tax is not None else None,
    )


# ── document-level tax ───────────────────────────────────────────
def test_a_bottom_line_tax_figure_is_spread_back_onto_the_lines():
    """Bills print one tax total; the voucher engine derives tax per line. Without
    this the saved bill would total less than the paper one."""
    lines = [line("20", "1200"), line("5", "8500")]      # 24,000 + 42,500 = 66,500
    _apply_document_tax(lines, {"tax_amount": 11305})     # 17% of 66,500

    assert all(l.tax_rate == Decimal("17.00") for l in lines)


def test_per_line_rates_win_over_the_document_total():
    """If the bill already breaks tax down per line, that is more precise."""
    lines = [line("1", "100", tax="5"), line("1", "100")]
    _apply_document_tax(lines, {"tax_amount": 34})

    assert lines[0].tax_rate == Decimal("5")
    assert lines[1].tax_rate is None


def test_no_tax_on_the_bill_leaves_the_lines_alone():
    lines = [line("1", "100")]
    _apply_document_tax(lines, {"tax_amount": 0})
    assert lines[0].tax_rate is None


def test_a_nonsense_tax_figure_is_ignored_rather_than_applied():
    """OCR misreads happen. A tax figure larger than the goods is not a rate we
    should quietly write onto every line."""
    lines = [line("1", "100")]
    _apply_document_tax(lines, {"tax_amount": 5000})   # would imply 5000%
    assert lines[0].tax_rate is None


def test_a_zero_value_line_cannot_cause_a_divide_by_zero():
    """A free or promotional line has rate 0, so the taxable base can be zero
    even though the bill printed a tax figure."""
    lines = [line("1", "0")]
    _apply_document_tax(lines, {"tax_amount": 100})
    assert lines[0].tax_rate is None


# ── arithmetic checks shown to the user ──────────────────────────
def test_line_totals_are_summed_from_amount_or_qty_times_rate():
    data = {"lines": [{"amount": 24000}, {"qty": 5, "rate": 8500}]}
    assert _sum_lines(data) == Decimal("66500.0000")


def test_a_total_that_disagrees_with_the_lines_is_surfaced():
    warnings = _warnings(
        {"confidence": 0.9, "lines": [{"amount": 1000}], "total": 9999}
    )
    assert any("add up to" in w for w in warnings)


def test_low_confidence_asks_the_user_to_check():
    warnings = _warnings({"confidence": 0.4, "lines": [{"amount": 10}]})
    assert any("Low confidence" in w for w in warnings)


def test_unreadable_fields_are_named_individually():
    warnings = _warnings(
        {"confidence": 0.9, "lines": [{"amount": 10}], "unreadable_fields": ["invoice_date"]}
    )
    assert "Could not read: invoice_date" in warnings


# ── endpoint contract ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_scan_rejects_text_too_short_to_be_a_bill(shop):
    response = await shop["client"].post("/ai/ocr/scan", json={"raw_text": "abc"})
    assert response.status_code == 422
    assert "raw_text" in str(response.json()["error"]["details"])


@pytest.mark.asyncio
async def test_scan_requires_text_not_just_an_attachment(shop):
    """The image alone is no longer enough — recognition happens on the device."""
    response = await shop["client"].post("/ai/ocr/scan", json={"attachment_id": "whatever"})
    assert response.status_code == 422
