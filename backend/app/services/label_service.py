"""Barcode labels: a printable sheet of them, sized to real sticker stock."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from jinja2 import Environment, select_autoescape
from markupsafe import Markup
from sqlalchemy import select

from app.core.barcodes import BarcodeError, encode
from app.core.errors import BusinessRuleError, NotFoundError
from app.core.money import format_money
from app.models.business import Business
from app.models.item import Item
from app.services.base import ActorContext

_env = Environment(autoescape=select_autoescape(["html", "xml"]), trim_blocks=True,
                   lstrip_blocks=True)


@dataclass(frozen=True)
class LabelSize:
    """A sticker sheet, by the numbers printed on its own box.

    Shops buy label stock by these names, so the app should offer the names
    rather than asking for millimetres nobody has to hand.
    """

    key: str
    name: str
    label_width_mm: float
    label_height_mm: float
    columns: int
    rows: int
    page: str = "A4"
    page_margin_mm: float = 8.0
    gap_mm: float = 2.0

    def __post_init__(self) -> None:
        # Every measurement is rendered straight into CSS, so they are coerced
        # here rather than left as whatever literal was typed in the table —
        # "38mm" and "38.0mm" are the same length but not the same string, and
        # anything checking the output would be checking the literal.
        for field in ("label_width_mm", "label_height_mm", "page_margin_mm", "gap_mm"):
            object.__setattr__(self, field, float(getattr(self, field)))

    @property
    def per_sheet(self) -> int:
        return self.columns * self.rows

    @property
    def is_roll(self) -> bool:
        """Continuous stock: one label per page, fed by a label printer."""
        return self.columns == 1 and self.rows == 1


LABEL_SIZES: dict[str, LabelSize] = {
    size.key: size
    for size in (
        # The common A4 sticker sheets sold in Pakistan and India.
        LabelSize("a4_65", "A4 sheet · 65 labels (38×21 mm)", 38, 21, 5, 13),
        LabelSize("a4_48", "A4 sheet · 48 labels (45×21 mm)", 45, 21, 4, 12),
        LabelSize("a4_24", "A4 sheet · 24 labels (64×34 mm)", 64, 34, 3, 8),
        LabelSize("a4_12", "A4 sheet · 12 labels (97×42 mm)", 97, 42, 2, 6),
        # Direct-thermal roll stock for a dedicated label printer.
        LabelSize("roll_50x25", "Roll · 50×25 mm", 50, 25, 1, 1, page="50mm 25mm",
                  page_margin_mm=1.0, gap_mm=0),
        LabelSize("roll_38x25", "Roll · 38×25 mm", 38, 25, 1, 1, page="38mm 25mm",
                  page_margin_mm=1.0, gap_mm=0),
        LabelSize("roll_75x50", "Roll · 75×50 mm", 75, 50, 1, 1, page="75mm 50mm",
                  page_margin_mm=1.0, gap_mm=0),
    )
}

DEFAULT_SIZE = "a4_65"

SHEET_TEMPLATE = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Barcode labels</title>
<style>
  @page { size: {{ size.page }}; margin: {{ size.page_margin_mm }}mm; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  .sheet {
    display: grid;
    grid-template-columns: repeat({{ size.columns }}, {{ size.label_width_mm }}mm);
    gap: {{ size.gap_mm }}mm;
    justify-content: center;
  }
  .label {
    width: {{ size.label_width_mm }}mm;
    height: {{ size.label_height_mm }}mm;
    padding: 1mm;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    /* Every label is its own box, so one long product name cannot push the
       next label off its sticker and misalign the entire sheet. */
    break-inside: avoid;
    page-break-inside: avoid;
  }
  {% if size.is_roll %}
  .label { page-break-after: always; }
  .label:last-child { page-break-after: auto; }
  {% endif %}
  .shop { font-size: {{ scale(5.5) }}pt; font-weight: 700; line-height: 1.1;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          max-width: 100%; }
  .name { font-size: {{ scale(6.5) }}pt; font-weight: 600; line-height: 1.1;
          max-height: {{ scale(14) }}pt; overflow: hidden; }
  .price { font-size: {{ scale(8) }}pt; font-weight: 800; line-height: 1.2; }
  .mrp { font-size: {{ scale(5.5) }}pt; }
  .code { font-size: {{ scale(5) }}pt; letter-spacing: 0.4px;
          font-family: ui-monospace, "Courier New", monospace; }
  .bars { width: 100%; line-height: 0; }
  .bars svg { width: 100%; height: {{ barcode_height_mm }}mm; display: block; }
  .missing { font-size: {{ scale(5) }}pt; color: #b00; }
  @media screen {
    body { background: #f4f4f5; padding: 10mm; }
    .sheet { background: #fff; padding: {{ size.page_margin_mm }}mm;
             box-shadow: 0 1px 6px rgba(0,0,0,.15); }
  }
</style>
</head><body>
<div class="sheet">
{% for label in labels %}
  <div class="label">
    {% if label.show_shop and shop_name %}<div class="shop">{{ shop_name }}</div>{% endif %}
    {% if label.show_name %}<div class="name">{{ label.name }}</div>{% endif %}
    {% if label.svg %}<div class="bars">{{ label.svg }}</div>{% endif %}
    {% if label.error %}<div class="missing">{{ label.error }}</div>{% endif %}
    {% if label.show_code and label.code %}<div class="code">{{ label.code }}</div>{% endif %}
    {% if label.show_price %}<div class="price">{{ label.price }}</div>{% endif %}
    {% if label.show_mrp and label.mrp %}<div class="mrp">MRP {{ label.mrp }}</div>{% endif %}
  </div>
{% endfor %}
</div>
</body></html>
"""


class LabelService:
    """Builds the printable sheet. Nothing here writes to the database."""

    def __init__(self, db, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def render(
        self,
        requests: list[dict[str, Any]],
        *,
        size_key: str = DEFAULT_SIZE,
        show_name: bool = True,
        show_price: bool = True,
        show_mrp: bool = False,
        show_code: bool = True,
        show_shop: bool = False,
        start_at: int = 1,
    ) -> str:
        """Render `qty` labels for each requested item.

        `start_at` skips positions on a part-used sheet — a shop that printed
        nine labels yesterday should not have to waste the rest of the sticker
        paper to print one more today.
        """
        size = LABEL_SIZES.get(size_key)
        if size is None:
            raise BusinessRuleError(
                f"Unknown label size '{size_key}'.",
                details={"available": sorted(LABEL_SIZES)},
            )
        if not requests:
            raise BusinessRuleError("Choose at least one item to print labels for.")

        # Summed rather than assigned: the same item listed twice means "print
        # three and also four", and a dict comprehension would silently keep
        # only the last of them.
        wanted: dict[str, int] = {}
        for row in requests:
            item_id = str(row["item_id"])
            wanted[item_id] = wanted.get(item_id, 0) + max(0, int(row.get("qty") or 1))

        total = sum(wanted.values())
        if total <= 0:
            raise BusinessRuleError("Set how many labels to print.")
        if total > 1000:
            raise BusinessRuleError(
                f"{total} labels is more than one job. Print up to 1000 at a time."
            )

        items = (
            await self.db.execute(
                select(Item).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.id.in_(list(wanted)),
                )
            )
        ).scalars().all()
        found = {item.id: item for item in items}

        missing = [i for i in wanted if i not in found]
        if missing:
            raise NotFoundError("Item not found.", details={"id": missing[0]})

        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one_or_none()
        symbol = getattr(business, "currency_symbol", None) or "Rs "

        labels: list[dict[str, Any]] = []

        # Blanks for the positions already peeled off a part-used sheet.
        for _ in range(max(0, min(start_at - 1, size.per_sheet - 1))):
            labels.append({"blank": True, "show_name": False, "show_price": False,
                           "show_mrp": False, "show_code": False, "show_shop": False,
                           "svg": None, "error": None, "name": "", "code": None,
                           "price": "", "mrp": None})

        for item_id, qty in wanted.items():
            item = found[item_id]
            svg, error, code = self._barcode_for(item, size)
            for _ in range(max(0, qty)):
                labels.append(
                    {
                        "blank": False,
                        "name": item.name,
                        "code": code,
                        "price": format_money(item.sale_price, symbol=symbol, decimals=0),
                        "mrp": (
                            format_money(item.mrp, symbol=symbol, decimals=0)
                            if item.mrp
                            else None
                        ),
                        "svg": svg,
                        "error": error,
                        "show_name": show_name,
                        "show_price": show_price,
                        "show_mrp": show_mrp,
                        "show_code": show_code,
                        "show_shop": show_shop,
                    }
                )

        template = _env.from_string(SHEET_TEMPLATE)
        return template.render(
            size=size,
            labels=labels,
            shop_name=getattr(business, "name", "") or "",
            barcode_height_mm=self._barcode_height(size),
            scale=self._scale_for(size),
        )

    def preview(self, size_key: str = DEFAULT_SIZE) -> LabelSize:
        size = LABEL_SIZES.get(size_key)
        if size is None:
            raise BusinessRuleError(f"Unknown label size '{size_key}'.")
        return size

    def _barcode_for(
        self, item: Item, size: LabelSize
    ) -> tuple[Markup | None, str | None, str | None]:
        """The bars for one item, or a readable reason there are none.

        An item with no barcode still gets a label — the name and price are
        worth printing on their own — and says so on the sticker rather than
        leaving a blank a shopkeeper would take for a printer fault.
        """
        raw = (item.barcode or item.sku or "").strip()
        if not raw:
            return None, "no barcode", None

        try:
            symbol = encode(raw)
        except BarcodeError as error:
            return None, str(error)[:40], raw

        return (
            Markup(  # noqa: S704 — SVG is built here, not from user input
                symbol.to_svg(
                    width_mm=size.label_width_mm - 2,
                    height_mm=self._barcode_height(size),
                )
            ),
            None,
            symbol.value,
        )

    @staticmethod
    def _barcode_height(size: LabelSize) -> float:
        """Bars take roughly a third of the sticker, floored at a readable 6mm.

        Below about 5mm a hand scanner starts missing them at an angle, which
        reads as an intermittent fault rather than as a label that is too small.
        """
        return max(6.0, min(size.label_height_mm * 0.38, 18.0))

    @staticmethod
    def _scale_for(size: LabelSize):
        """Type scales with the sticker so a 38mm label is not set in 8pt."""
        factor = max(0.75, min(size.label_height_mm / 21.0, 1.8))
        return lambda points: round(points * factor, 1)
