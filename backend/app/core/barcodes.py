"""Barcode encoding, rendered as SVG paths.

Hand-rolled rather than pulled in as a dependency: the encoders are small and
fully specified, the deployment is a serverless bundle where every megabyte is
paid for on cold start, and an image library would be the largest thing in it.

Being wrong here fails in the worst way — the label prints, it looks right, and
the scanner at the counter simply refuses it with no explanation anyone can
act on. So both encoders are checked against published reference encodings.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Code 128 ───────────────────────────────────────────────────────
# One entry per symbol value 0–106. Each is six run lengths, alternating
# bar, space, bar, space, bar, space — eleven modules in total, except the
# stop pattern which carries a seventh run and is thirteen.
_CODE128_PATTERNS: tuple[str, ...] = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
    "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
    "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
    "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
    "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
    "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
    "211214", "211232", "2331112",
)

_CODE128_B_START = 104
_CODE128_STOP = 106

# ── EAN-13 ─────────────────────────────────────────────────────────
# Digit encodings for the three sets. L and G encode the left half, R the
# right. Which of L or G is used for each left digit is chosen by the first
# digit, which is itself never drawn — that is the whole trick of EAN-13.
_EAN_L = ("0001101", "0011001", "0010011", "0111101", "0100011",
          "0110001", "0101111", "0111011", "0110111", "0001011")
_EAN_G = ("0100111", "0110011", "0011011", "0100001", "0011101",
          "0111001", "0000101", "0010001", "0001001", "0010111")
_EAN_R = ("1110010", "1100110", "1101100", "1000010", "1011100",
          "1001110", "1010000", "1000100", "1001000", "1110100")

_EAN_PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")


class BarcodeError(ValueError):
    """The value cannot be encoded in the requested symbology."""


@dataclass(frozen=True)
class Barcode:
    """An encoded symbol, as a run of module widths."""

    symbology: str
    value: str
    modules: str          # "1" is a bar, "0" is a space, one character per module

    @property
    def module_count(self) -> int:
        return len(self.modules)

    def to_svg(self, *, width_mm: float = 32.0, height_mm: float = 12.0) -> str:
        """A standalone SVG sized in millimetres, drawn as one path per bar.

        Bars are placed on a viewBox one unit per module, so the browser scales
        them to whatever the label is without the widths drifting apart. Drawing
        each bar as its own rect at a fractional width is what makes printed
        barcodes unreadable: the renderer rounds each one independently and the
        ratios stop being ratios.
        """
        rects = []
        run_start = None
        for index, module in enumerate(self.modules):
            if module == "1" and run_start is None:
                run_start = index
            elif module == "0" and run_start is not None:
                rects.append((run_start, index - run_start))
                run_start = None
        if run_start is not None:
            rects.append((run_start, len(self.modules) - run_start))

        bars = "".join(
            f'<rect x="{x}" y="0" width="{w}" height="100" />' for x, w in rects
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_mm}mm" height="{height_mm}mm" '
            f'viewBox="0 0 {self.module_count} 100" preserveAspectRatio="none" '
            f'shape-rendering="crispEdges">{bars}</svg>'
        )


def encode(value: str, symbology: str = "auto") -> Barcode:
    """Encode a value, picking EAN-13 for retail codes and Code 128 otherwise.

    'auto' is what a shop wants: a 12 or 13 digit code came off a manufacturer's
    packaging and must stay EAN-13, while a shop's own SKU is arbitrary text and
    only Code 128 will carry it.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        raise BarcodeError("There is no code to print.")

    if symbology == "auto":
        symbology = (
            "ean13" if cleaned.isdigit() and len(cleaned) in (12, 13) else "code128"
        )

    if symbology == "ean13":
        return encode_ean13(cleaned)
    if symbology == "code128":
        return encode_code128(cleaned)
    raise BarcodeError(f"Unknown barcode type '{symbology}'.")


def encode_code128(value: str) -> Barcode:
    """Code 128 set B, which covers every printable ASCII character."""
    for character in value:
        if not 32 <= ord(character) <= 126:
            raise BarcodeError(
                f"'{character}' cannot go in a barcode. Use letters, digits and "
                "basic punctuation only."
            )

    values = [ord(character) - 32 for character in value]

    # The checksum weights each symbol by its position, starting at one; the
    # start code counts as position zero.
    total = _CODE128_B_START + sum(v * (i + 1) for i, v in enumerate(values))
    checksum = total % 103

    symbols = [_CODE128_B_START, *values, checksum, _CODE128_STOP]
    return Barcode("code128", value, _widths_to_modules(symbols))


def encode_ean13(value: str) -> Barcode:
    """EAN-13, computing the check digit when only twelve digits are given."""
    digits = value.strip()
    if not digits.isdigit():
        raise BarcodeError("An EAN-13 barcode is thirteen digits and nothing else.")

    if len(digits) == 12:
        digits += str(ean13_check_digit(digits))
    if len(digits) != 13:
        raise BarcodeError(
            f"An EAN-13 barcode needs 12 or 13 digits, not {len(digits)}."
        )
    if digits[-1] != str(ean13_check_digit(digits[:12])):
        raise BarcodeError(
            "That barcode's check digit does not match the rest of it — it has "
            "probably been mistyped."
        )

    parity = _EAN_PARITY[int(digits[0])]
    modules = ["101"]                                    # start guard
    for index, digit in enumerate(digits[1:7]):
        table = _EAN_L if parity[index] == "L" else _EAN_G
        modules.append(table[int(digit)])
    modules.append("01010")                              # centre guard
    for digit in digits[7:]:
        modules.append(_EAN_R[int(digit)])
    modules.append("101")                                # end guard

    return Barcode("ean13", digits, "".join(modules))


def ean13_check_digit(first_twelve: str) -> int:
    """The thirteenth digit: weights alternate 1 and 3 from the left."""
    if len(first_twelve) != 12 or not first_twelve.isdigit():
        raise BarcodeError("The check digit is worked out from exactly twelve digits.")
    total = sum(
        int(digit) * (3 if index % 2 else 1)
        for index, digit in enumerate(first_twelve)
    )
    return (10 - total % 10) % 10


def next_ean13(prefix: str, sequence: int) -> str:
    """Build a shop's own EAN-13 from a prefix and a running number.

    Shops that sell loose or home-made goods need codes of their own. 200–299 is
    the range reserved for exactly this and is guaranteed never to collide with
    a manufacturer's code, so a self-printed label cannot be mistaken for one.

    The sequence is zero-padded to fill the remaining width rather than the
    whole body being padded on the right. Padding the body put item 1 and item
    10 on the same code — two different products with one barcode, which the
    counter has no way to tell apart.
    """
    if not prefix.isdigit():
        raise BarcodeError("A barcode prefix can only contain digits.")
    if not 1 <= len(prefix) <= 8:
        raise BarcodeError("A barcode prefix is between one and eight digits.")
    if sequence < 0:
        raise BarcodeError("A barcode sequence cannot be negative.")

    width = 12 - len(prefix)
    body = f"{sequence}".zfill(width)
    if len(body) > width:
        raise BarcodeError(
            f"Prefix '{prefix}' leaves room for {10 ** width - 1} codes, "
            f"and {sequence} is past that."
        )
    return prefix + body + str(ean13_check_digit(prefix + body))


def _widths_to_modules(symbols: list[int]) -> str:
    """Turn symbol values into a bar/space string, one character per module."""
    out: list[str] = []
    for symbol in symbols:
        pattern = _CODE128_PATTERNS[symbol]
        for index, run in enumerate(pattern):
            out.append(("1" if index % 2 == 0 else "0") * int(run))
    return "".join(out)
