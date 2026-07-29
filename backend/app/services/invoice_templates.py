"""Invoice looks.

Four, because shops print for different reasons: one to hand across a counter,
one to attach to an email, one a wholesaler files for GST, and one that fits a
receipt roll. They share the same data and the same Jinja variables — only the
layout differs, so adding a fifth is a template, not a code change.

All four are self-contained HTML with inline CSS. Nothing loads a font or an
image from the network: an invoice has to render identically on a phone with no
signal and inside an email client that blocks remote content.
"""

from __future__ import annotations

# ── shared pieces ────────────────────────────────────────────────
_BASE_CSS = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         color: #1a1a1a; margin: 0; font-size: 12px; line-height: 1.45; }
  table { width: 100%; border-collapse: collapse; }
  .r { text-align: right; }
  .c { text-align: center; }
  .muted { color: #666; }
  .b { font-weight: 700; }
  .nums { font-variant-numeric: tabular-nums; }
"""

_ITEMS_ROWS = """
  {% for line in v.lines %}
  <tr>
    <td class="c">{{ loop.index }}</td>
    <td>
      {{ line.item_name }}
      {% if line.description %}<div class="muted">{{ line.description }}</div>{% endif %}
    </td>
    {% if show_hsn %}<td class="c">{{ line.hsn_code or '' }}</td>{% endif %}
    <td class="r nums">{{ line.qty | qty }} {{ line.unit_label }}</td>
    <td class="r nums">{{ line.rate | money }}</td>
    {% if has_discount %}<td class="r nums">{{ line.discount_amount | money }}</td>{% endif %}
    {% if has_tax %}<td class="r nums">{{ line.tax_rate | qty }}%</td>{% endif %}
    <td class="r nums b">{{ line.total | money }}</td>
  </tr>
  {% endfor %}
"""

_TOTALS = """
  <tr><td class="muted">Subtotal</td><td class="r nums">{{ v.subtotal | money }}</td></tr>
  {% if v.discount_amount %}
  <tr><td class="muted">Discount</td><td class="r nums">-{{ v.discount_amount | money }}</td></tr>
  {% endif %}
  {% if v.tax_amount %}
  <tr><td class="muted">Tax</td><td class="r nums">{{ v.tax_amount | money }}</td></tr>
  {% endif %}
  {% if v.shipping_charge %}
  <tr><td class="muted">Delivery</td><td class="r nums">{{ v.shipping_charge | money }}</td></tr>
  {% endif %}
  {% if v.round_off %}
  <tr><td class="muted">Round off</td><td class="r nums">{{ v.round_off | money }}</td></tr>
  {% endif %}
"""


# ── 1. Classic ───────────────────────────────────────────────────
# The default: a coloured header band, everything on one page. What most
# shopkeepers expect an invoice to look like.
CLASSIC = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ doc_title }} {{ v.number }}</title>
<style>
  @page { size: {{ page_size }}; margin: 12mm 10mm; }
  __CSS__
  .band { background: {{ theme }}; color: #fff; padding: 14px 16px; border-radius: 8px; }
  .band h1 { margin: 0; font-size: 20px; letter-spacing: .5px; }
  .meta { display: flex; justify-content: space-between; margin: 16px 0; gap: 20px; }
  thead th { background: #f4f4f5; padding: 7px 8px; text-align: left;
             border-bottom: 2px solid {{ theme }}; font-size: 11px; text-transform: uppercase; }
  tbody td { padding: 7px 8px; border-bottom: 1px solid #eee; }
  .totals { width: 45%; margin-left: auto; margin-top: 12px; }
  .totals td { padding: 4px 8px; }
  .grand { background: {{ theme }}; color: #fff; font-size: 15px; font-weight: 800; }
  .foot { margin-top: 24px; border-top: 1px solid #ddd; padding-top: 10px; font-size: 11px; }
</style></head><body>

<div class="band">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <h1>{{ biz.name }}</h1>
      <div style="opacity:.9">{{ biz.address_line1 or '' }}{% if biz.phone %} · {{ biz.phone }}{% endif %}</div>
      {% if biz.gstin or biz.ntn %}<div style="opacity:.9">{{ tax_label }}: {{ biz.gstin or biz.ntn }}</div>{% endif %}
    </div>
    <div class="r"><div style="font-size:16px;font-weight:800">{{ doc_title }}</div></div>
  </div>
</div>

<div class="meta">
  <div>
    <div class="muted">Billed to</div>
    <div class="b" style="font-size:14px">{{ v.party_name or 'Walk-in customer' }}</div>
    {% if v.party_phone %}<div class="muted">{{ v.party_phone }}</div>{% endif %}
  </div>
  <div class="r">
    <div><span class="muted">No.</span> <span class="b">{{ v.number }}</span></div>
    <div><span class="muted">Date</span> {{ v.voucher_date }}</div>
    {% if v.due_date %}<div><span class="muted">Due</span> {{ v.due_date }}</div>{% endif %}
  </div>
</div>

<table>
  <thead><tr>
    <th class="c">#</th><th>Item</th>
    {% if show_hsn %}<th class="c">HSN</th>{% endif %}
    <th class="r">Qty</th><th class="r">Rate</th>
    {% if has_discount %}<th class="r">Disc</th>{% endif %}
    {% if has_tax %}<th class="r">Tax</th>{% endif %}
    <th class="r">Amount</th>
  </tr></thead>
  <tbody>__ROWS__</tbody>
</table>

<table class="totals">
  __TOTALS__
  <tr class="grand"><td>TOTAL</td><td class="r nums">{{ v.total | money }}</td></tr>
  {% if v.paid_amount %}
  <tr><td class="muted">Paid</td><td class="r nums">{{ v.paid_amount | money }}</td></tr>
  <tr class="b"><td>Balance due</td><td class="r nums">{{ v.balance_amount | money }}</td></tr>
  {% endif %}
</table>

{% if show_words %}<div style="margin-top:10px" class="muted">Amount in words: <b>{{ words }}</b></div>{% endif %}

<div class="foot">
  {% if bank %}<div><b>Bank:</b> {{ bank.name }} · {{ bank.account_number or '' }}</div>{% endif %}
  {% if terms %}<div style="margin-top:6px">{{ terms }}</div>{% endif %}
  {% if footer %}<div style="margin-top:6px">{{ footer }}</div>{% endif %}
  <div style="margin-top:14px;display:flex;justify-content:space-between">
    <span class="muted">This is a computer-generated {{ doc_title | lower }}.</span>
    <span>For {{ biz.name }}</span>
  </div>
</div>
</body></html>
""".replace("__CSS__", _BASE_CSS).replace("__ROWS__", _ITEMS_ROWS).replace("__TOTALS__", _TOTALS)


# ── 2. Minimal ───────────────────────────────────────────────────
# No colour at all. Prints legibly on a tired inkjet and photographs well for
# WhatsApp, which is how most of these actually reach the customer.
MINIMAL = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ doc_title }} {{ v.number }}</title>
<style>
  @page { size: {{ page_size }}; margin: 14mm 12mm; }
  __CSS__
  body { font-size: 12.5px; }
  h1 { font-size: 17px; margin: 0 0 2px; letter-spacing: 1px; }
  .rule { border-top: 2px solid #111; margin: 12px 0; }
  .thin { border-top: 1px solid #ccc; margin: 10px 0; }
  thead th { padding: 6px 4px; text-align: left; border-bottom: 1px solid #111;
             font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
  tbody td { padding: 6px 4px; }
  .totals { width: 50%; margin-left: auto; }
  .totals td { padding: 3px 4px; }
  .grand td { border-top: 2px solid #111; font-size: 15px; font-weight: 800; padding-top: 8px; }
</style></head><body>

<h1>{{ biz.name }}</h1>
<div class="muted">
  {{ biz.address_line1 or '' }}{% if biz.phone %} · {{ biz.phone }}{% endif %}
  {% if biz.gstin or biz.ntn %} · {{ tax_label }} {{ biz.gstin or biz.ntn }}{% endif %}
</div>
<div class="rule"></div>

<table><tr>
  <td>
    <div class="b">{{ doc_title }}</div>
    <div>{{ v.party_name or 'Walk-in customer' }}</div>
    {% if v.party_phone %}<div class="muted">{{ v.party_phone }}</div>{% endif %}
  </td>
  <td class="r">
    <div>{{ v.number }}</div>
    <div class="muted">{{ v.voucher_date }}</div>
    {% if v.due_date %}<div class="muted">Due {{ v.due_date }}</div>{% endif %}
  </td>
</tr></table>

<div class="thin"></div>
<table>
  <thead><tr>
    <th class="c">#</th><th>Item</th>
    {% if show_hsn %}<th class="c">HSN</th>{% endif %}
    <th class="r">Qty</th><th class="r">Rate</th>
    {% if has_discount %}<th class="r">Disc</th>{% endif %}
    {% if has_tax %}<th class="r">Tax</th>{% endif %}
    <th class="r">Amount</th>
  </tr></thead>
  <tbody>__ROWS__</tbody>
</table>

<table class="totals">
  __TOTALS__
  <tr class="grand"><td>TOTAL</td><td class="r nums">{{ v.total | money }}</td></tr>
  {% if v.paid_amount %}
  <tr><td class="muted">Paid</td><td class="r nums">{{ v.paid_amount | money }}</td></tr>
  <tr class="b"><td>Balance</td><td class="r nums">{{ v.balance_amount | money }}</td></tr>
  {% endif %}
</table>

{% if show_words %}<div style="margin-top:8px" class="muted">{{ words }}</div>{% endif %}
{% if terms %}<div class="thin"></div><div class="muted">{{ terms }}</div>{% endif %}
<div style="margin-top:26px" class="r">For {{ biz.name }}</div>
</body></html>
""".replace("__CSS__", _BASE_CSS).replace("__ROWS__", _ITEMS_ROWS).replace("__TOTALS__", _TOTALS)


# ── 3. GST / tax invoice ─────────────────────────────────────────
# What a registered wholesaler's accountant expects: both parties' GSTINs, place
# of supply, and tax broken into CGST/SGST or IGST rather than one figure.
GST = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ doc_title }} {{ v.number }}</title>
<style>
  @page { size: {{ page_size }}; margin: 10mm 8mm; }
  __CSS__
  body { font-size: 11px; }
  .box { border: 1px solid #333; }
  .box td { border: 1px solid #333; padding: 5px 7px; vertical-align: top; }
  .title { text-align: center; font-size: 15px; font-weight: 800;
           letter-spacing: 1px; padding: 6px; border-bottom: 1px solid #333; }
  thead th { border: 1px solid #333; padding: 5px; background: #f2f2f2;
             font-size: 10px; text-transform: uppercase; }
  tbody td { border: 1px solid #333; padding: 5px; }
  .totals td { border: 1px solid #333; padding: 4px 7px; }
  .grand { font-size: 13px; font-weight: 800; background: #f2f2f2; }
</style></head><body>

<div class="box">
  <div class="title">{{ doc_title }}</div>
  <table><tr>
    <td style="width:55%">
      <div class="b" style="font-size:13px">{{ biz.name }}</div>
      <div>{{ biz.address_line1 or '' }}</div>
      {% if biz.city %}<div>{{ biz.city }}{% if biz.state %}, {{ biz.state }}{% endif %}</div>{% endif %}
      {% if biz.gstin or biz.ntn %}<div><b>{{ tax_label }}:</b> {{ biz.gstin or biz.ntn }}</div>{% endif %}
      {% if biz.phone %}<div>Ph: {{ biz.phone }}</div>{% endif %}
    </td>
    <td>
      <div><b>Invoice no:</b> {{ v.number }}</div>
      <div><b>Date:</b> {{ v.voucher_date }}</div>
      {% if v.due_date %}<div><b>Due:</b> {{ v.due_date }}</div>{% endif %}
      {% if v.reference_number %}<div><b>Ref:</b> {{ v.reference_number }}</div>{% endif %}
      <div><b>Place of supply:</b> {{ place_of_supply or '—' }}</div>
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <div class="muted" style="font-size:10px">BILL TO</div>
      <div class="b">{{ v.party_name or 'Walk-in customer' }}</div>
      {% if v.party_gstin %}<div><b>{{ tax_label }}:</b> {{ v.party_gstin }}</div>{% endif %}
      {% if v.party_phone %}<div>{{ v.party_phone }}</div>{% endif %}
    </td>
  </tr></table>
</div>

<table style="margin-top:8px">
  <thead><tr>
    <th class="c">#</th><th>Description</th><th class="c">HSN</th>
    <th class="r">Qty</th><th class="r">Rate</th><th class="r">Taxable</th>
    {% if is_interstate %}<th class="r">IGST</th>{% else %}<th class="r">CGST</th><th class="r">SGST</th>{% endif %}
    <th class="r">Total</th>
  </tr></thead>
  <tbody>
  {% for line in v.lines %}
  <tr>
    <td class="c">{{ loop.index }}</td>
    <td>{{ line.item_name }}</td>
    <td class="c">{{ line.hsn_code or '' }}</td>
    <td class="r nums">{{ line.qty | qty }} {{ line.unit_label }}</td>
    <td class="r nums">{{ line.rate | money }}</td>
    <td class="r nums">{{ line.taxable_amount | money }}</td>
    {% if is_interstate %}
    <td class="r nums">{{ line.igst_amount | money }}<div class="muted">{{ line.tax_rate | qty }}%</div></td>
    {% else %}
    <td class="r nums">{{ line.cgst_amount | money }}</td>
    <td class="r nums">{{ line.sgst_amount | money }}</td>
    {% endif %}
    <td class="r nums b">{{ line.total | money }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>

<table class="totals" style="width:48%;margin-left:auto;margin-top:8px">
  <tr><td>Taxable value</td><td class="r nums">{{ v.taxable_amount | money }}</td></tr>
  {% if v.discount_amount %}<tr><td>Discount</td><td class="r nums">-{{ v.discount_amount | money }}</td></tr>{% endif %}
  {% if is_interstate %}
  <tr><td>IGST</td><td class="r nums">{{ v.igst_amount | money }}</td></tr>
  {% else %}
  <tr><td>CGST</td><td class="r nums">{{ v.cgst_amount | money }}</td></tr>
  <tr><td>SGST</td><td class="r nums">{{ v.sgst_amount | money }}</td></tr>
  {% endif %}
  {% if v.round_off %}<tr><td>Round off</td><td class="r nums">{{ v.round_off | money }}</td></tr>{% endif %}
  <tr class="grand"><td>TOTAL</td><td class="r nums">{{ v.total | money }}</td></tr>
</table>

{% if show_words %}
<div style="margin-top:8px"><b>Amount in words:</b> {{ words }}</div>
{% endif %}

<table class="box" style="margin-top:10px"><tr>
  <td style="width:60%">
    {% if bank %}
    <div class="b">Bank details</div>
    <div>{{ bank.name }}{% if bank.account_number %} · A/c {{ bank.account_number }}{% endif %}</div>
    {% if bank.ifsc %}<div>IFSC: {{ bank.ifsc }}</div>{% endif %}
    {% endif %}
    {% if terms %}<div style="margin-top:6px" class="muted">{{ terms }}</div>{% endif %}
  </td>
  <td class="c">
    <div style="height:46px"></div>
    <div>For <b>{{ biz.name }}</b></div>
    <div class="muted" style="font-size:10px">Authorised signatory</div>
  </td>
</tr></table>
</body></html>
""".replace("__CSS__", _BASE_CSS)


# ── 4. Receipt ───────────────────────────────────────────────────
# 80mm wide, for a thermal roll driven through the OS print dialog rather than
# ESC/POS. Narrow single column; nothing that assumes horizontal room.
RECEIPT = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ v.number }}</title>
<style>
  @page { size: 80mm auto; margin: 4mm; }
  __CSS__
  body { width: 72mm; font-size: 11px; font-family: "Courier New", monospace; }
  .c { text-align: center; }
  .line { border-top: 1px dashed #000; margin: 6px 0; }
  td { padding: 2px 0; }
  .big { font-size: 15px; font-weight: 800; }
</style></head><body>

<div class="c">
  <div class="big">{{ biz.name }}</div>
  {% if biz.address_line1 %}<div>{{ biz.address_line1 }}</div>{% endif %}
  {% if biz.phone %}<div>{{ biz.phone }}</div>{% endif %}
  {% if biz.gstin or biz.ntn %}<div>{{ tax_label }}: {{ biz.gstin or biz.ntn }}</div>{% endif %}
</div>

<div class="line"></div>
<table>
  <tr><td>{{ v.number }}</td><td class="r">{{ v.voucher_date }}</td></tr>
  {% if v.party_name %}<tr><td colspan="2">{{ v.party_name }}</td></tr>{% endif %}
</table>
<div class="line"></div>

<table>
{% for line in v.lines %}
  <tr><td colspan="2">{{ line.item_name }}</td></tr>
  <tr>
    <td class="muted">{{ line.qty | qty }} {{ line.unit_label }} x {{ line.rate | money }}</td>
    <td class="r nums">{{ line.total | money }}</td>
  </tr>
{% endfor %}
</table>

<div class="line"></div>
<table>
  <tr><td>Subtotal</td><td class="r nums">{{ v.subtotal | money }}</td></tr>
  {% if v.discount_amount %}<tr><td>Discount</td><td class="r nums">-{{ v.discount_amount | money }}</td></tr>{% endif %}
  {% if v.tax_amount %}<tr><td>Tax</td><td class="r nums">{{ v.tax_amount | money }}</td></tr>{% endif %}
  <tr class="big"><td>TOTAL</td><td class="r nums">{{ v.total | money }}</td></tr>
  {% if v.paid_amount %}
  <tr><td>Paid</td><td class="r nums">{{ v.paid_amount | money }}</td></tr>
  <tr class="b"><td>Balance</td><td class="r nums">{{ v.balance_amount | money }}</td></tr>
  {% endif %}
</table>

<div class="line"></div>
{% if footer %}<div class="c">{{ footer }}</div>{% endif %}
<div class="c b" style="margin-top:6px">Thank you!</div>
</body></html>
""".replace("__CSS__", _BASE_CSS)


TEMPLATES = {
    "classic": CLASSIC,
    "minimal": MINIMAL,
    "gst": GST,
    "receipt": RECEIPT,
}

# Shown in Settings, so a shopkeeper picks by what it is for, not by its name.
TEMPLATE_LABELS = {
    "classic": "Classic — coloured header, one page",
    "minimal": "Minimal — black and white, prints anywhere",
    "gst": "GST invoice — both GSTINs, CGST/SGST split",
    "receipt": "Receipt — 80mm roll",
}


def get(name: str | None) -> str:
    """Falls back to Classic: an unknown name in the database must not stop an
    invoice from printing."""
    return TEMPLATES.get((name or "").lower(), CLASSIC)
