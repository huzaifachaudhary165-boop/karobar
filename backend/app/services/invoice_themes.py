"""Invoice themes.

A theme is a small description — a layout family, a palette, a paper size and a
density — rendered by one parameterised template. Twenty near-identical copies
of the same HTML would be twenty places for the same bug to hide and twenty
files to change when a tax column moves; the parts that actually differ between
one shop's invoice and another's are the ones named here.

Every theme is self-contained HTML with inline CSS. Nothing loads a font or an
image from the network: a bill has to look the same on a phone with no signal
and inside an email client that blocks remote content.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── layout families ────────────────────────────────────────────────
# These are the structural differences. Everything else a theme changes is
# colour, type and spacing, which the one template handles from variables.
BAND = "band"              # coloured header band across the top
SIDEBAR = "sidebar"        # accent stripe down the left, header inside it
PLAIN = "plain"            # rules and type only, no fills — cheapest to print
LETTERHEAD = "letterhead"  # top left blank for pre-printed paper
ROLL = "roll"              # continuous receipt paper

LAYOUTS = (BAND, SIDEBAR, PLAIN, LETTERHEAD, ROLL)


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    layout: str
    accent: str = "#F97316"
    ink: str = "#1a1a1a"
    font: str = "sans"          # sans | serif | mono
    density: str = "regular"    # regular | compact | roomy
    paper: str = "A4"
    rules: bool = True          # horizontal rules between item rows
    zebra: bool = False         # shaded alternate rows
    uppercase_headings: bool = True

    @property
    def is_roll(self) -> bool:
        return self.layout == ROLL

    @property
    def font_stack(self) -> str:
        return {
            "serif": 'Georgia, "Times New Roman", "Noto Serif", serif',
            "mono": 'ui-monospace, "Courier New", monospace',
        }.get(self.font, '-apple-system, "Segoe UI", Roboto, Arial, sans-serif')

    @property
    def base_pt(self) -> float:
        """Body size. A compact theme fits a wholesaler's forty-line bill on
        one page; a roomy one is for a shop that bills three things at a time."""
        return {"compact": 10.0, "roomy": 13.0}.get(self.density, 11.5)

    @property
    def row_padding(self) -> str:
        return {"compact": "3px 5px", "roomy": "9px 8px"}.get(self.density, "6px 6px")

    @property
    def page_margin(self) -> str:
        if self.is_roll:
            return "2mm"
        return {"compact": "8mm", "roomy": "16mm"}.get(self.density, "12mm 10mm")


# The named themes. Grouped by what a shop is printing for, because that is how
# the choice is actually made — not by which colour someone likes today.
THEMES: dict[str, Theme] = {
    theme.key: theme
    for theme in (
        # ── everyday counter bills ─────────────────────────────────
        Theme("classic", "Classic — orange header", BAND, "#F97316"),
        Theme("classic_blue", "Classic — blue header", BAND, "#2563EB"),
        Theme("classic_green", "Classic — green header", BAND, "#16A34A"),
        Theme("classic_maroon", "Classic — maroon header", BAND, "#9F1239"),
        Theme("classic_teal", "Classic — teal header", BAND, "#0D9488"),
        Theme("classic_slate", "Classic — charcoal header", BAND, "#334155"),

        # ── a stripe instead of a band ─────────────────────────────
        Theme("modern", "Modern — orange side stripe", SIDEBAR, "#F97316"),
        Theme("modern_indigo", "Modern — indigo side stripe", SIDEBAR, "#4F46E5"),
        Theme("modern_rose", "Modern — rose side stripe", SIDEBAR, "#E11D48"),
        Theme("modern_amber", "Modern — amber side stripe", SIDEBAR, "#D97706"),

        # ── black and white, cheapest to print ─────────────────────
        Theme("minimal", "Minimal — black and white", PLAIN, "#1a1a1a", rules=False),
        Theme("minimal_lines", "Minimal — ruled rows", PLAIN, "#1a1a1a"),
        Theme("minimal_zebra", "Minimal — shaded rows", PLAIN, "#1a1a1a", zebra=True),
        Theme("mono", "Typewriter — monospaced figures", PLAIN, "#1a1a1a", font="mono"),

        # ── for services and consultants ───────────────────────────
        Theme("elegant", "Elegant — serif, generous spacing", PLAIN, "#1a1a1a",
              font="serif", density="roomy"),
        Theme("elegant_navy", "Elegant — serif, navy rules", PLAIN, "#1E3A5F",
              font="serif", density="roomy"),

        # ── wholesalers, long bills ────────────────────────────────
        Theme("compact", "Compact — fits a long bill on one page", PLAIN, "#1a1a1a",
              density="compact", zebra=True),
        Theme("compact_band", "Compact — with a header band", BAND, "#334155",
              density="compact", zebra=True),

        # ── pre-printed stationery ─────────────────────────────────
        Theme("letterhead", "Letterhead — leaves the top blank", LETTERHEAD, "#1a1a1a"),
        Theme("letterhead_accent", "Letterhead — with a rule in your colour",
              LETTERHEAD, "#F97316"),

        # ── other paper sizes ──────────────────────────────────────
        Theme("a5", "A5 — half sheet", BAND, "#F97316", paper="A5", density="compact"),
        Theme("a5_plain", "A5 — half sheet, plain", PLAIN, "#1a1a1a", paper="A5",
              density="compact"),
        Theme("letter", "US Letter", BAND, "#F97316", paper="Letter"),

        # ── thermal rolls ──────────────────────────────────────────
        Theme("receipt", "Receipt — 80mm roll", ROLL, "#1a1a1a", paper="80mm auto",
              density="compact", font="mono"),
        Theme("receipt_58", "Receipt — 58mm roll", ROLL, "#1a1a1a", paper="58mm auto",
              density="compact", font="mono"),
        Theme("receipt_wide", "Receipt — 80mm, larger type", ROLL, "#1a1a1a",
              paper="80mm auto", font="mono"),
    )
}

DEFAULT_THEME = "classic"


def get_theme(key: str | None, accent: str | None = None) -> Theme:
    """Resolve a theme, falling back rather than refusing to print.

    An unknown name reaches here from a settings row written by an older build,
    and a bill that will not print is a far worse answer than one that prints in
    the default look.
    """
    theme = THEMES.get((key or "").lower().strip(), THEMES[DEFAULT_THEME])
    # A shop's own colour overrides the theme's, except where the theme is
    # deliberately monochrome — a black-and-white layout tinted orange is
    # neither of the two things someone chose.
    if accent and theme.accent != "#1a1a1a":
        theme = Theme(**{**theme.__dict__, "accent": accent})
    return theme


THEME_TEMPLATE = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ doc_title }} {{ v.number }}</title>
<style>
  @page { size: {{ t.paper }}; margin: {{ t.page_margin }}; }
  * { box-sizing: border-box; }
  body { font-family: {{ t.font_stack }}; color: {{ t.ink }}; margin: 0;
         font-size: {{ t.base_pt }}pt; line-height: 1.45; }
  table { width: 100%; border-collapse: collapse; }
  .r { text-align: right; } .c { text-align: center; }
  .muted { color: #666; } .b { font-weight: 700; }
  .nums { font-variant-numeric: tabular-nums; }
  h1, h2, .heading { {% if t.uppercase_headings %}text-transform: uppercase;
       letter-spacing: .5px;{% endif %} margin: 0; }

  {% if t.layout == 'band' %}
  .head { background: {{ t.accent }}; color: #fff; padding: 10mm 8mm 7mm;
          margin: -{{ t.page_margin.split(' ')[0] }} -{{ t.page_margin.split(' ')[-1] }} 6mm; }
  .head .muted { color: rgba(255,255,255,.85); }
  .doc { font-size: {{ (t.base_pt * 1.5)|round(1) }}pt; font-weight: 800; }
  {% elif t.layout == 'sidebar' %}
  body { border-left: 6mm solid {{ t.accent }}; padding-left: 6mm; }
  .head { padding-bottom: 5mm; border-bottom: 2px solid {{ t.accent }}; margin-bottom: 6mm; }
  .doc { font-size: {{ (t.base_pt * 1.5)|round(1) }}pt; font-weight: 800;
         color: {{ t.accent }}; }
  {% elif t.layout == 'letterhead' %}
  /* Nothing at the top: the shop's own paper already has it printed there. */
  .head { margin-top: 38mm; padding-bottom: 4mm;
          border-bottom: 2px solid {{ t.accent }}; margin-bottom: 6mm; }
  .doc { font-size: {{ (t.base_pt * 1.4)|round(1) }}pt; font-weight: 800; }
  .head .shopname { display: none; }
  {% elif t.layout == 'roll' %}
  body { width: 100%; }
  .head { text-align: center; padding-bottom: 3mm; margin-bottom: 3mm;
          border-bottom: 1px dashed #999; }
  .doc { font-size: {{ (t.base_pt * 1.2)|round(1) }}pt; font-weight: 800; }
  .cols { display: none; }
  {% else %}
  .head { padding-bottom: 4mm; border-bottom: 2px solid {{ t.accent }};
          margin-bottom: 6mm; }
  .doc { font-size: {{ (t.base_pt * 1.4)|round(1) }}pt; font-weight: 800; }
  {% endif %}

  .cols { display: flex; gap: 8mm; margin-bottom: 5mm; }
  .cols > div { flex: 1; }
  .label { font-size: {{ (t.base_pt * 0.8)|round(1) }}pt; color: #666;
           letter-spacing: .4px; text-transform: uppercase; }

  .items th { text-align: left; padding: {{ t.row_padding }};
              font-size: {{ (t.base_pt * 0.85)|round(1) }}pt;
              {% if t.layout in ('band', 'sidebar') %}
              background: {{ t.accent }}22; color: {{ t.ink }};
              {% else %}border-bottom: 1.5px solid {{ t.ink }};{% endif %} }
  .items td { padding: {{ t.row_padding }};
              {% if t.rules %}border-bottom: 1px solid #e5e5e5;{% endif %} }
  {% if t.zebra %}.items tbody tr:nth-child(even) { background: #f6f6f7; }{% endif %}

  .totals { width: {% if t.is_roll %}100%{% else %}62mm{% endif %};
            margin-left: auto; margin-top: 4mm; }
  .totals td { padding: 2px 4px; }
  .grand td { border-top: 2px solid {{ t.accent }}; padding-top: 5px;
              font-size: {{ (t.base_pt * 1.15)|round(1) }}pt; font-weight: 800; }
  .foot { margin-top: 7mm; font-size: {{ (t.base_pt * 0.85)|round(1) }}pt; color: #555; }
  .sign { margin-top: 12mm; text-align: right; }
  .sign span { border-top: 1px solid #999; padding-top: 3px; display: inline-block;
               min-width: 45mm; text-align: center; }
</style>
</head><body>

<div class="head">
  <table><tr>
    <td>
      <div class="shopname b" style="font-size: {{ (t.base_pt * 1.3)|round(1) }}pt;">
        {{ biz.name }}</div>
      {% if biz.address_line1 %}<div class="muted">{{ biz.address_line1 }}</div>{% endif %}
      {% if biz.phone %}<div class="muted">{{ biz.phone }}</div>{% endif %}
      {% if biz.gstin or biz.ntn %}
      <div class="muted">{{ tax_label }}: {{ biz.gstin or biz.ntn }}</div>
      {% endif %}
    </td>
    <td class="r">
      <div class="doc">{{ doc_title }}</div>
      <div class="b nums">{{ v.number }}</div>
      <div class="muted nums">{{ v.voucher_date }}</div>
      {% if v.due_date %}<div class="muted nums">Due {{ v.due_date }}</div>{% endif %}
    </td>
  </tr></table>
</div>

{% if v.party_name %}
<div class="cols">
  <div>
    <div class="label">{{ party_label }}</div>
    <div class="b">{{ v.party_name }}</div>
    {% if v.party_phone %}<div class="muted">{{ v.party_phone }}</div>{% endif %}
    {% if v.billing_address %}<div class="muted">{{ v.billing_address }}</div>{% endif %}
  </div>
  {% if place_of_supply %}
  <div class="r"><div class="label">Place of supply</div><div>{{ place_of_supply }}</div></div>
  {% endif %}
</div>
{% elif t.is_roll and v.party_name %}
<div class="b">{{ v.party_name }}</div>
{% endif %}

<table class="items">
  <thead><tr>
    {% if not t.is_roll %}<th class="c" style="width:8mm">#</th>{% endif %}
    <th>Item</th>
    {% if show_hsn %}<th class="c">HSN</th>{% endif %}
    <th class="r">Qty</th>
    <th class="r">Rate</th>
    {% if has_discount %}<th class="r">Disc</th>{% endif %}
    {% if has_tax and not t.is_roll %}<th class="r">Tax</th>{% endif %}
    <th class="r">Amount</th>
  </tr></thead>
  <tbody>
  {% for line in v.lines %}
    <tr>
      {% if not t.is_roll %}<td class="c muted">{{ loop.index }}</td>{% endif %}
      <td>{{ line.item_name }}
        {% if line.description %}<div class="muted">{{ line.description }}</div>{% endif %}
      </td>
      {% if show_hsn %}<td class="c">{{ line.hsn_code or '' }}</td>{% endif %}
      <td class="r nums">{{ line.qty | qty }} {{ line.unit_label }}</td>
      <td class="r nums">{{ line.rate | money }}</td>
      {% if has_discount %}<td class="r nums">{{ line.discount_amount | money }}</td>{% endif %}
      {% if has_tax and not t.is_roll %}<td class="r nums">{{ line.tax_rate | qty }}%</td>{% endif %}
      <td class="r nums b">{{ line.total | money }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<table class="totals">
  <tr><td class="muted">Subtotal</td><td class="r nums">{{ v.subtotal | money }}</td></tr>
  {% if v.discount_amount %}
  <tr><td class="muted">Discount</td><td class="r nums">-{{ v.discount_amount | money }}</td></tr>
  {% endif %}
  {% if is_interstate and v.igst_amount %}
  <tr><td class="muted">IGST</td><td class="r nums">{{ v.igst_amount | money }}</td></tr>
  {% elif v.cgst_amount %}
  <tr><td class="muted">CGST</td><td class="r nums">{{ v.cgst_amount | money }}</td></tr>
  <tr><td class="muted">SGST</td><td class="r nums">{{ v.sgst_amount | money }}</td></tr>
  {% elif v.tax_amount %}
  <tr><td class="muted">Tax</td><td class="r nums">{{ v.tax_amount | money }}</td></tr>
  {% endif %}
  {% if v.shipping_charge %}
  <tr><td class="muted">Delivery</td><td class="r nums">{{ v.shipping_charge | money }}</td></tr>
  {% endif %}
  {% if v.round_off %}
  <tr><td class="muted">Round off</td><td class="r nums">{{ v.round_off | money }}</td></tr>
  {% endif %}
  <tr class="grand"><td>Total</td><td class="r nums">{{ v.total | money }}</td></tr>
  {% if v.paid_amount %}
  <tr><td class="muted">Paid</td><td class="r nums">{{ v.paid_amount | money }}</td></tr>
  <tr><td class="b">Balance</td><td class="r nums b">{{ v.balance_amount | money }}</td></tr>
  {% endif %}
</table>

{% if show_words and words %}
<div class="foot b">{{ words }}</div>
{% endif %}

{% if bank and not t.is_roll %}
<div class="foot">
  <span class="label">Pay into</span><br>
  {{ bank.name }}{% if bank.bank_name %} · {{ bank.bank_name }}{% endif %}
  {% if bank.account_number %}<br>A/C {{ bank.account_number }}{% endif %}
  {% if bank.iban %}<br>IBAN {{ bank.iban }}{% endif %}
</div>
{% endif %}

{% if terms and not t.is_roll %}<div class="foot">{{ terms }}</div>{% endif %}
{% if footer %}<div class="foot {% if t.is_roll %}c{% endif %}">{{ footer }}</div>{% endif %}

{% if qr %}
<div class="foot {% if t.is_roll %}c{% endif %}">
  <img src="{{ qr }}" width="90" height="90" alt="">
</div>
{% endif %}

{% if not t.is_roll and t.layout != 'letterhead' %}
<div class="sign"><span>Authorised signature</span></div>
{% endif %}

</body></html>
"""
