"""Invoice rendering. Returns print-ready HTML always, PDF bytes when WeasyPrint
is installed. The Flutter client can render the HTML to PDF locally, so a server
without GTK is not a blocker.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from jinja2 import Environment, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.logging import log
from app.core.money import amount_in_words, format_money
from app.models.business import Business, BusinessSettings
from app.models.payment import Account
from app.models.voucher import Voucher
from app.services.base import ActorContext
from app.services.invoice_templates import TEMPLATE_LABELS, get as template_for

_env = Environment(autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)

DOC_TITLES = {
    "sale": "TAX INVOICE",
    "purchase": "PURCHASE BILL",
    "sale_return": "CREDIT NOTE",
    "purchase_return": "DEBIT NOTE",
    "quotation": "QUOTATION",
    "proforma": "PROFORMA INVOICE",
    "delivery_challan": "DELIVERY CHALLAN",
    "sale_order": "SALE ORDER",
    "purchase_order": "PURCHASE ORDER",
}

INVOICE_TEMPLATE = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ doc_title }} {{ v.number }}</title>
<style>
  @page { size: {{ page_size }}; margin: 12mm 10mm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         color: #1a1a1a; font-size: 11px; margin: 0; }
  .sheet { max-width: 190mm; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: flex-start;
           border-bottom: 3px solid {{ theme }}; padding-bottom: 10px; }
  .biz-name { font-size: 20px; font-weight: 700; color: {{ theme }}; margin: 0 0 2px; }
  .muted { color: #666; }
  .doc-tag { text-align: right; }
  .doc-tag h2 { margin: 0; font-size: 15px; letter-spacing: 1.5px; color: {{ theme }}; }
  .doc-no { font-size: 13px; font-weight: 700; margin-top: 3px; }
  .logo { max-height: 54px; max-width: 150px; }
  .parties { display: flex; gap: 14px; margin: 14px 0; }
  .party { flex: 1; border: 1px solid #e3e3e3; border-radius: 6px; padding: 9px 11px; }
  .party h3 { margin: 0 0 5px; font-size: 9px; text-transform: uppercase;
              letter-spacing: 1px; color: #888; }
  .party .n { font-weight: 700; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  thead th { background: {{ theme }}; color: #fff; padding: 7px 8px; text-align: left;
             font-size: 10px; font-weight: 600; }
  tbody td { padding: 7px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
  tbody tr:nth-child(even) { background: #fcfcfc; }
  .r { text-align: right; }
  .c { text-align: center; }
  .totals { margin-top: 12px; display: flex; justify-content: flex-end; }
  .totals table { width: 265px; }
  .totals td { padding: 4px 8px; border: none; }
  .totals .grand td { border-top: 2px solid {{ theme }}; font-size: 14px;
                      font-weight: 700; color: {{ theme }}; padding-top: 7px; }
  .words { margin-top: 9px; font-style: italic; color: #555; font-size: 10px; }
  .blocks { display: flex; gap: 14px; margin-top: 16px; }
  .block { flex: 1; font-size: 10px; }
  .block h4 { margin: 0 0 4px; font-size: 9px; text-transform: uppercase;
              letter-spacing: 1px; color: #888; }
  .sign { margin-top: 34px; text-align: right; }
  .sign .line { border-top: 1px solid #999; width: 165px; display: inline-block;
                padding-top: 4px; }
  footer { margin-top: 20px; padding-top: 8px; border-top: 1px solid #eee;
           text-align: center; color: #999; font-size: 9px; }
  .badge { display: inline-block; padding: 2px 9px; border-radius: 10px;
           font-size: 9px; font-weight: 700; text-transform: uppercase; }
  .paid { background: #e6f7ec; color: #1a7f43; }
  .due  { background: #fdecea; color: #b3261e; }
</style></head>
<body><div class="sheet">
  <header>
    <div>
      {% if biz.logo_url %}<img class="logo" src="{{ biz.logo_url }}" alt="">{% endif %}
      <p class="biz-name">{{ biz.name }}</p>
      {% if biz.full_address %}<div class="muted">{{ biz.full_address }}</div>{% endif %}
      {% if biz.phone %}<div class="muted">Phone: {{ biz.phone }}</div>{% endif %}
      {% if biz.email %}<div class="muted">{{ biz.email }}</div>{% endif %}
      {% if biz.tax_number %}<div class="muted"><b>{{ tax_label }}:</b> {{ biz.tax_number }}</div>{% endif %}
    </div>
    <div class="doc-tag">
      <h2>{{ doc_title }}</h2>
      <div class="doc-no">{{ v.number }}</div>
      <div class="muted">Date: {{ v.voucher_date.strftime('%d %b %Y') }}</div>
      {% if v.due_date %}<div class="muted">Due: {{ v.due_date.strftime('%d %b %Y') }}</div>{% endif %}
      <div style="margin-top:5px">
        <span class="badge {{ 'paid' if v.is_paid else 'due' }}">
          {{ 'PAID' if v.is_paid else v.status|upper }}
        </span>
      </div>
    </div>
  </header>

  <div class="parties">
    <div class="party">
      <h3>Bill To</h3>
      <div class="n">{{ v.party_name or 'Walk-in Customer' }}</div>
      {% if v.billing_address %}<div class="muted">{{ v.billing_address }}</div>{% endif %}
      {% if v.party_phone %}<div class="muted">{{ v.party_phone }}</div>{% endif %}
      {% if v.party_gstin %}<div class="muted">{{ tax_label }}: {{ v.party_gstin }}</div>{% endif %}
    </div>
    {% if v.shipping_address %}
    <div class="party">
      <h3>Ship To</h3>
      <div class="muted">{{ v.shipping_address }}</div>
    </div>
    {% endif %}
  </div>

  <table>
    <thead><tr>
      <th style="width:26px">#</th>
      <th>Item</th>
      {% if show_hsn %}<th style="width:64px">HSN</th>{% endif %}
      <th class="c" style="width:62px">Qty</th>
      <th class="r" style="width:76px">Rate</th>
      {% if has_discount %}<th class="r" style="width:66px">Disc.</th>{% endif %}
      {% if has_tax %}<th class="r" style="width:66px">Tax</th>{% endif %}
      <th class="r" style="width:88px">Amount</th>
    </tr></thead>
    <tbody>
    {% for line in v.lines %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>
          <b>{{ line.item_name }}</b>
          {% if line.description %}<div class="muted">{{ line.description }}</div>{% endif %}
        </td>
        {% if show_hsn %}<td>{{ line.hsn_code or '-' }}</td>{% endif %}
        <td class="c">{{ line.qty|qty }} {{ line.unit_label }}</td>
        <td class="r">{{ line.rate|money }}</td>
        {% if has_discount %}<td class="r">{{ line.discount_amount|money }}</td>{% endif %}
        {% if has_tax %}<td class="r">{{ line.tax_amount|money }}</td>{% endif %}
        <td class="r"><b>{{ line.total|money }}</b></td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="totals"><table>
    <tr><td>Subtotal</td><td class="r">{{ v.subtotal|money }}</td></tr>
    {% if v.discount_amount %}
      <tr><td>Discount</td><td class="r">- {{ v.discount_amount|money }}</td></tr>{% endif %}
    {% if v.cgst_amount %}
      <tr><td>CGST</td><td class="r">{{ v.cgst_amount|money }}</td></tr>
      <tr><td>SGST</td><td class="r">{{ v.sgst_amount|money }}</td></tr>{% endif %}
    {% if v.igst_amount %}
      <tr><td>IGST</td><td class="r">{{ v.igst_amount|money }}</td></tr>{% endif %}
    {% if v.cess_amount %}
      <tr><td>Cess</td><td class="r">{{ v.cess_amount|money }}</td></tr>{% endif %}
    {% if not v.cgst_amount and not v.igst_amount and v.tax_amount %}
      <tr><td>Tax</td><td class="r">{{ v.tax_amount|money }}</td></tr>{% endif %}
    {% if v.shipping_charge %}
      <tr><td>Shipping</td><td class="r">{{ v.shipping_charge|money }}</td></tr>{% endif %}
    {% if v.packaging_charge %}
      <tr><td>Packaging</td><td class="r">{{ v.packaging_charge|money }}</td></tr>{% endif %}
    {% if v.round_off %}
      <tr><td>Round off</td><td class="r">{{ v.round_off|money }}</td></tr>{% endif %}
    <tr class="grand"><td>Total</td><td class="r">{{ v.total|money }}</td></tr>
    {% if v.paid_amount %}
      <tr><td>Paid</td><td class="r">{{ v.paid_amount|money }}</td></tr>
      <tr><td><b>Balance Due</b></td><td class="r"><b>{{ v.balance_amount|money }}</b></td></tr>
    {% endif %}
  </table></div>

  {% if show_words %}<div class="words">{{ words }}</div>{% endif %}

  <div class="blocks">
    <div class="block">
      {% if bank %}
        <h4>Bank Details</h4>
        <div><b>{{ bank.bank_name or bank.name }}</b></div>
        {% if bank.account_number %}<div>A/C: {{ bank.account_number }}</div>{% endif %}
        {% if bank.iban %}<div>IBAN: {{ bank.iban }}</div>{% endif %}
        {% if bank.ifsc %}<div>IFSC: {{ bank.ifsc }}</div>{% endif %}
        {% if bank.upi_id %}<div>UPI: {{ bank.upi_id }}</div>{% endif %}
      {% endif %}
      {% if v.notes %}<h4 style="margin-top:9px">Notes</h4><div>{{ v.notes }}</div>{% endif %}
    </div>
    <div class="block">
      {% if v.terms %}<h4>Terms &amp; Conditions</h4><div>{{ v.terms }}</div>{% endif %}
    </div>
    <div class="block">
      {% if qr %}<img src="{{ qr }}" alt="" style="width:88px;height:88px">{% endif %}
      <div class="sign">
        {% if biz.signature_url %}
          <img src="{{ biz.signature_url }}" style="max-height:44px" alt=""><br>{% endif %}
        <span class="line">For {{ biz.name }}</span>
      </div>
    </div>
  </div>

  <footer>
    {{ footer or 'This is a computer-generated document.' }}
    &nbsp;·&nbsp; Generated by Karobar
  </footer>
</div></body></html>
"""


class PdfService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def render_html(self, voucher_id: str) -> str:
        voucher, business, cfg, bank = await self._load(voucher_id)
        symbol = f"{business.currency_symbol} "

        env = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
        env.filters["money"] = lambda v: format_money(v or 0, symbol=symbol)
        env.filters["qty"] = lambda v: (
            str(int(v)) if v is not None and v == int(v) else f"{v:.2f}"
        )

        # `invoice_template` is a free-text setting, so an unknown value must
        # fall back rather than stop the bill printing.
        template = template_for(cfg.invoice_template)

        return env.from_string(template).render(
            v=voucher,
            biz=business,
            theme=business.theme_color or "#F97316",
            doc_title=DOC_TITLES.get(voucher.voucher_type, voucher.voucher_type.upper()),
            tax_label="GSTIN" if business.gstin else "NTN",
            page_size="A5" if cfg.print_size == "A5" else "A4",
            show_hsn=cfg.show_hsn and any(line.hsn_code for line in voucher.lines),
            has_discount=any(line.discount_amount for line in voucher.lines),
            has_tax=bool(voucher.tax_amount),
            show_words=cfg.show_amount_in_words,
            words=amount_in_words(
                voucher.total,
                currency="Rupees" if business.currency in ("PKR", "INR") else business.currency,
            ),
            bank=bank,
            qr=self._qr(voucher, business) if cfg.show_qr_code else None,
            footer=cfg.invoice_footer,
            terms=cfg.terms_and_conditions,
            # Interstate is what decides IGST vs CGST+SGST on the tax layout.
            # Derived from the voucher's own split rather than re-guessed here,
            # so the printed breakdown always matches what was actually posted.
            is_interstate=bool(voucher.igst_amount),
            place_of_supply=voucher.place_of_supply,
        )

    async def render_pdf(self, voucher_id: str) -> bytes | None:
        """Returns PDF bytes, or None when WeasyPrint is unavailable on this host."""
        html = await self.render_html(voucher_id)
        try:
            from weasyprint import HTML  # noqa: PLC0415 — optional dependency

            buffer = io.BytesIO()
            HTML(string=html).write_pdf(buffer)
            return buffer.getvalue()
        except ImportError:
            log.info("pdf.weasyprint_unavailable")
            return None
        except Exception as exc:  # pragma: no cover
            log.error("pdf.render_failed", error=str(exc)[:300])
            return None

    async def _load(self, voucher_id: str):
        voucher = (
            await self.db.execute(
                select(Voucher).where(
                    Voucher.id == voucher_id,
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if voucher is None:
            raise NotFoundError("Invoice not found.", details={"id": voucher_id})

        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(BusinessSettings.business_id == self.business_id)
            )
        ).scalar_one_or_none() or BusinessSettings(business_id=self.business_id)
        bank = (
            await self.db.execute(
                select(Account).where(
                    Account.business_id == self.business_id,
                    Account.show_on_invoice.is_(True),
                    Account.is_deleted.is_(False),
                ).limit(1)
            )
        ).scalar_one_or_none()
        return voucher, business, cfg, bank

    def _qr(self, voucher: Voucher, business: Business) -> str | None:
        """Data-URI QR carrying the invoice reference, for quick lookup/UPI apps."""
        try:
            import qrcode  # noqa: PLC0415

            payload = (
                f"{business.name}|{voucher.number}|{voucher.total}|"
                f"{voucher.voucher_date.isoformat()}"
            )
            img = qrcode.make(payload)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/png;base64,{encoded}"
        except Exception:
            return None
