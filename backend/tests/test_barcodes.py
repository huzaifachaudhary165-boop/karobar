"""Barcode encoding, checked against published reference symbols.

This is the one place in the app where being wrong is silent. The label prints,
it looks exactly like a barcode, and the scanner at the counter refuses it with
nothing anyone can act on. So the encodings below are pinned to references
rather than to whatever the code happens to produce.
"""

from __future__ import annotations

import pytest

from app.core.barcodes import (
    Barcode, BarcodeError, ean13_check_digit, encode, encode_code128, encode_ean13,
    next_ean13,
)


# ── EAN-13 ─────────────────────────────────────────────────────────
def test_the_check_digit_matches_a_known_product_code():
    # 5901234123457 is the example carried in the EAN-13 specification itself.
    assert ean13_check_digit("590123412345") == 7


@pytest.mark.parametrize(
    "first_twelve,expected",
    [
        ("400638133393", 1),   # a German retail code
        ("978014300723", 4),   # ISBN-13 of a paperback
        ("012345678901", 2),
        ("000000000000", 0),
    ],
)
def test_check_digits_across_known_codes(first_twelve, expected):
    assert ean13_check_digit(first_twelve) == expected


def test_an_ean13_symbol_is_the_right_length():
    # 3 guard + 6×7 + 5 centre + 6×7 + 3 guard = 95 modules, always.
    symbol = encode_ean13("5901234123457")
    assert symbol.module_count == 95


def test_an_ean13_symbol_starts_and_ends_with_its_guards():
    modules = encode_ean13("5901234123457").modules
    assert modules.startswith("101")
    assert modules.endswith("101")
    assert modules[45:50] == "01010", "the centre guard sits at the halfway point"


def test_the_first_digit_is_carried_by_the_parity_not_by_bars():
    """The whole trick of EAN-13: twelve digits are drawn, thirteen are read.

    Both codes below encode the same six digits in their left half — 012345 —
    and the bars there still differ, because the first digit chooses which of
    the two left-hand alphabets each of those six is drawn from.
    """
    one = encode_ean13("0012345678905").modules
    two = encode_ean13("5012345678900").modules

    assert one[3:45] != two[3:45], "the first digit must change the left half"
    assert one[45:50] == two[45:50] == "01010", "the centre guard never moves"


def test_twelve_digits_are_completed_rather_than_refused():
    symbol = encode_ean13("590123412345")
    assert symbol.value == "5901234123457"


def test_a_mistyped_check_digit_is_caught(shop=None):
    with pytest.raises(BarcodeError, match="mistyped"):
        encode_ean13("5901234123450")


def test_letters_are_not_an_ean13():
    with pytest.raises(BarcodeError):
        encode_ean13("59012341234A")


def test_the_wrong_number_of_digits_is_refused():
    with pytest.raises(BarcodeError, match="12 or 13"):
        encode_ean13("12345")


# ── Code 128 ───────────────────────────────────────────────────────
def test_a_code128_symbol_is_the_right_length():
    # start + n data + checksum = 11 modules each, plus a 13-module stop.
    for value in ("A", "AB", "SKU-0001", "Hello, world!"):
        symbol = encode_code128(value)
        assert symbol.module_count == 11 * (len(value) + 2) + 13, value


def test_the_code128_checksum_matches_the_worked_example():
    """'PJJ123C', worked out by hand from the specification.

    Set B values are the character minus 32, so P J J 1 2 3 C are
    48 42 42 17 18 19 35. Each is weighted by its position starting at one,
    and the start code counts as position zero:

        104 + 48·1 + 42·2 + 42·3 + 17·4 + 18·5 + 19·6 + 35·7 = 879

    and 879 mod 103 is 55.
    """
    values = [ord(c) - 32 for c in "PJJ123C"]
    assert values == [48, 42, 42, 17, 18, 19, 35]

    total = 104 + sum(v * (i + 1) for i, v in enumerate(values))
    assert total == 879
    assert total % 103 == 55

    # The check symbol is the second-to-last, occupying its own eleven modules
    # before the thirteen-module stop.
    symbol = encode_code128("PJJ123C")
    assert symbol.modules[-24:-13] == encode_code128_symbol_modules(55)


def encode_code128_symbol_modules(value: int) -> str:
    """Renders one Code 128 symbol, for asserting on a single position."""
    from app.core.barcodes import _CODE128_PATTERNS

    out = []
    for index, run in enumerate(_CODE128_PATTERNS[value]):
        out.append(("1" if index % 2 == 0 else "0") * int(run))
    return "".join(out)


def test_a_code128_symbol_starts_with_the_set_b_start_code():
    symbol = encode_code128("X")
    assert symbol.modules[:11] == encode_code128_symbol_modules(104)


def test_a_code128_symbol_ends_with_the_stop_pattern():
    symbol = encode_code128("X")
    assert symbol.modules[-13:] == "1100011101011"


def test_every_code128_symbol_begins_with_a_bar_and_ends_with_a_bar():
    """A symbol that starts on a space has no quiet-zone edge to find."""
    for value in ("A", "SKU-42", "0000000"):
        modules = encode_code128(value).modules
        assert modules[0] == "1" and modules[-1] == "1", value


def test_characters_outside_ascii_are_refused_with_a_readable_reason():
    with pytest.raises(BarcodeError, match="cannot go in a barcode"):
        encode_code128("چینی")


def test_an_empty_value_is_refused():
    with pytest.raises(BarcodeError):
        encode("")
    with pytest.raises(BarcodeError):
        encode("   ")


# ── picking the symbology ──────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [
        ("5901234123457", "ean13"),   # a manufacturer's code stays EAN-13
        ("590123412345", "ean13"),    # twelve digits is one short of one
        ("SKU-0001", "code128"),      # a shop's own code is arbitrary text
        ("12345", "code128"),         # too short to be EAN-13
        ("12345678901234", "code128"),
    ],
)
def test_auto_picks_the_symbology_a_shop_would_expect(value, expected):
    assert encode(value).symbology == expected


def test_an_unknown_symbology_is_refused():
    with pytest.raises(BarcodeError, match="Unknown barcode type"):
        encode("12345", symbology="qr")


# ── a shop's own codes ─────────────────────────────────────────────
def test_a_shop_code_lands_in_the_range_reserved_for_it():
    """200–299 is reserved for in-store use and can never collide with a
    manufacturer's code, so a self-printed label is not mistaken for one."""
    code = next_ean13("200", 1)
    assert code.startswith("200")
    assert len(code) == 13
    assert ean13_check_digit(code[:12]) == int(code[-1])


def test_shop_codes_are_distinct_and_all_valid():
    """Item 1 and item 10 shared a code until the sequence was zero-padded
    into the remaining width instead of the whole body being padded right —
    two different products with one barcode, indistinguishable at the counter."""
    codes = {next_ean13("201", n) for n in range(1, 500)}
    assert len(codes) == 499
    for code in codes:
        assert encode_ean13(code).value == code


def test_the_sequence_fills_the_width_left_by_the_prefix():
    assert next_ean13("201", 1).startswith("201000000001")
    assert next_ean13("201", 10).startswith("201000000010")
    assert next_ean13("20", 7).startswith("200000000007")


def test_running_past_what_the_prefix_allows_is_refused():
    # An eight-digit prefix leaves four, so 9999 codes and no more.
    assert next_ean13("20000000", 9999).startswith("200000009999")
    with pytest.raises(BarcodeError, match="past that"):
        next_ean13("20000000", 10000)


def test_a_prefix_long_enough_to_leave_no_room_is_refused():
    with pytest.raises(BarcodeError, match="one and eight digits"):
        next_ean13("200000000000", 1)


def test_a_non_numeric_prefix_is_refused():
    with pytest.raises(BarcodeError, match="only contain digits"):
        next_ean13("SHOP", 1)


# ── SVG output ─────────────────────────────────────────────────────
def test_the_svg_scales_by_viewbox_rather_than_by_fractional_widths():
    """Each bar drawn at a fractional width is rounded on its own by the
    renderer, and the ratios stop being ratios. One unit per module keeps
    them exact at any printed size."""
    symbol = encode_ean13("5901234123457")
    svg = symbol.to_svg(width_mm=32, height_mm=12)

    assert 'viewBox="0 0 95 100"' in svg
    assert 'width="32mm"' in svg and 'height="12mm"' in svg
    assert "preserveAspectRatio=\"none\"" in svg


def test_adjacent_bars_are_drawn_as_one_rect():
    """Two touching bars split into two rects leave a hairline the scanner
    reads as a space."""
    symbol = Barcode("test", "x", "110011")
    svg = symbol.to_svg()
    assert svg.count("<rect") == 2
    assert 'x="0" y="0" width="2"' in svg
    assert 'x="4" y="0" width="2"' in svg


def test_the_svg_carries_every_bar():
    symbol = encode_code128("SKU-1")
    svg = symbol.to_svg()
    bars_in_modules = symbol.modules.count("10") + (1 if symbol.modules.endswith("1") else 0)
    assert svg.count("<rect") == bars_in_modules
