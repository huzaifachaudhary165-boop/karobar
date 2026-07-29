"""Bill / receipt scanning: photo → structured draft → real purchase or expense.

The reading and the understanding are split across two machines:

  phone   Google ML Kit pulls raw text out of the photo, on-device. Free,
          unlimited, works with no signal, and the picture never leaves the
          handset unless the user also uploads it for their own records.
  server  The model turns that messy text into a validated draft, using a JSON
          schema so we get an object instead of prose to parse.

That split is why this works on a free AI plan at all — no vision model is
involved. It also means the expensive, error-prone half (character recognition)
happens where the photo already is.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ai_client
from app.ai.prompts import OCR_SYSTEM
from app.core.errors import AIError, BusinessRuleError, NotFoundError
from app.core.logging import log
from app.core.money import ZERO, D, money
from app.models.ai import OcrJob
from app.models.base import utcnow
from app.models.enums import OcrStatus, VoucherType
from app.models.system import Attachment
from app.schemas.payment import ExpenseCreate
from app.schemas.voucher import VoucherCreate, VoucherLineInput
from app.services.base import ActorContext
from app.services.expense_service import ExpenseService
from app.services.item_service import ItemService
from app.services.party_service import PartyService
from app.services.storage_service import StorageService
from app.services.voucher_service import VoucherService
from app.utils.dates import parse_date

# The extraction contract. Everything is nullable — a null beats a hallucination.
EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["purchase_bill", "sale_invoice", "receipt", "expense", "unknown"],
        },
        "vendor_name": {"type": ["string", "null"]},
        "vendor_phone": {"type": ["string", "null"]},
        "vendor_gstin": {"type": ["string", "null"], "description": "GSTIN / NTN / tax number."},
        "vendor_address": {"type": ["string", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "currency": {"type": ["string", "null"]},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "hsn_code": {"type": ["string", "null"]},
                    "qty": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "rate": {"type": ["number", "null"]},
                    "discount": {"type": ["number", "null"]},
                    "tax_rate": {"type": ["number", "null"]},
                    "amount": {"type": ["number", "null"]},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        "subtotal": {"type": ["number", "null"]},
        "discount": {"type": ["number", "null"]},
        "tax_amount": {"type": ["number", "null"]},
        "shipping": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "paid": {"type": ["number", "null"]},
        "balance": {"type": ["number", "null"]},
        "payment_mode": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"], "description": "Anything unclear or inconsistent."},
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Your overall confidence that this extraction is faithful.",
        },
        "unreadable_fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names of fields you could not read reliably.",
        },
    },
    "required": ["document_type", "lines", "confidence"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """\
Below is raw text pulled off a photograph of a bill by on-device OCR. Turn it into \
the structured object.

The text is machine-read, so expect it to be rough:
  * Table columns often collapse into one line, or split across several.
  * Digits get confused — 0/O, 1/l/I, 5/S, 8/B. Prefer a reading that makes the \
arithmetic work.
  * Headers, footers, shop slogans and stamp text are noise; ignore them.
  * Lines may arrive out of order.

Never invent a value. If a field is not in the text, leave it null and name it in \
`unreadable_fields`.

Then check yourself before answering:
  * Do the line amounts add up to the subtotal?
  * Does subtotal − discount + tax + shipping equal the printed total?
If a check fails, keep the figures as printed and describe the mismatch in `notes`.

Set `confidence` honestly: 0.9+ when the text is clean and the totals reconcile, \
0.5–0.7 when it is fragmentary or the arithmetic is off, below 0.5 when you are \
largely guessing.

--- RAW OCR TEXT ---
{text}
--- END ---
"""

# Enough text to cover a long itemised bill without burning the per-minute budget
# on a page of noise.
MAX_OCR_TEXT = 12_000


class OcrService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""
        self.storage = StorageService()

    # ── scan ─────────────────────────────────────────────────────
    async def scan(
        self,
        *,
        raw_text: str,
        attachment_id: str | None = None,
        document_type: str = "auto",
        auto_create: bool = False,
        auto_create_party: bool = True,
        auto_create_items: bool = False,
    ) -> OcrJob:
        """Structure text the device already read off a bill.

        `attachment_id` is optional and purely for the shopkeeper's records — if
        they chose to keep the photo, the job points at it. The scan itself does
        not need the image.
        """
        text = (raw_text or "").strip()
        if len(text) < 12:
            raise BusinessRuleError(
                "No readable text was found on that photo. Try again with more light, "
                "holding the bill flat and filling the frame.",
                details={"characters": len(text)},
            )

        attachment = None
        if attachment_id:
            attachment = (
                await self.db.execute(
                    select(Attachment).where(
                        Attachment.id == attachment_id,
                        Attachment.business_id == self.business_id,
                    )
                )
            ).scalar_one_or_none()
            if attachment is None:
                raise NotFoundError("Uploaded file not found.", details={"id": attachment_id})

        job = OcrJob(
            business_id=self.business_id,
            user_id=self.actor.user_id,
            document_type="purchase_bill" if document_type == "auto" else document_type,
            status=OcrStatus.PROCESSING,
            file_url=attachment.url if attachment else None,
            file_name=attachment.file_name if attachment else None,
            mime_type=attachment.mime_type if attachment else None,
            file_size=attachment.size_bytes if attachment else None,
        )
        self.db.add(job)
        await self.db.flush()

        started = time.perf_counter()
        try:
            result = await ai_client.complete(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": EXTRACT_PROMPT.format(text=text[:MAX_OCR_TEXT]),
                            }
                        ],
                    }
                ],
                system=OCR_SYSTEM,
                output_schema=EXTRACT_SCHEMA,
                effort="high",
            )
            if result.is_refusal:
                raise AIError("The document could not be processed.", code="ai_refused")

            extracted = _parse_json(result.text)
            if extracted is None:
                raise AIError("The scan returned an unreadable result.", code="ocr_parse_failed")

            job.extracted = extracted
            # Keep what the phone read, not what the model echoed — that is the
            # evidence you want when a figure comes out wrong.
            job.raw_text = text[:20000]
            job.confidence = D(extracted.get("confidence", 0))
            job.document_type = extracted.get("document_type") or job.document_type
            job.warnings = _warnings(extracted)
            job.field_confidence = {f: 0.0 for f in extracted.get("unreadable_fields", [])}
            job.input_tokens = result.input_tokens
            job.output_tokens = result.output_tokens
            job.status = OcrStatus.COMPLETED
            job.completed_at = utcnow()

            if vendor := extracted.get("vendor_name"):
                matches = await PartyService(self.db, self.actor).search_by_name(vendor, limit=1)
                if matches and matches[0][1] >= 0.75:
                    job.matched_party_id = matches[0][0].id

            if auto_create and job.confidence and job.confidence >= Decimal("0.75"):
                await self.apply(
                    job.id,
                    target="expense" if job.document_type in ("receipt", "expense") else "purchase",
                    create_missing_party=auto_create_party,
                    create_missing_items=auto_create_items,
                )
        except Exception as exc:  # noqa: BLE001 — a failed scan is a job state, not a 500
            job.status = OcrStatus.FAILED
            job.error = str(exc)[:1000]
            log.error("ocr.failed", job_id=job.id, error=str(exc)[:500])
        finally:
            job.processing_ms = int((time.perf_counter() - started) * 1000)

        await self.db.flush()
        return job

    # ── apply ────────────────────────────────────────────────────
    async def apply(
        self,
        job_id: str,
        *,
        target: str = "purchase",
        corrections: dict[str, Any] | None = None,
        create_missing_party: bool = True,
        create_missing_items: bool = True,
    ) -> OcrJob:
        job = await self.get(job_id)
        if job.status not in (OcrStatus.COMPLETED, OcrStatus.APPLIED):
            raise BusinessRuleError(
                "This scan is not ready to apply.", details={"status": job.status}
            )
        if job.created_voucher_id or job.created_expense_id:
            raise BusinessRuleError("This scan has already been turned into a record.")

        data = {**(job.extracted or {}), **(corrections or {})}

        if target == "expense":
            expense = await self._to_expense(data)
            job.created_expense_id = expense.id
        else:
            voucher = await self._to_voucher(
                data,
                voucher_type=VoucherType.PURCHASE if target == "purchase" else VoucherType.SALE,
                create_party=create_missing_party,
                create_items=create_missing_items,
            )
            job.created_voucher_id = voucher.id

        job.status = OcrStatus.APPLIED
        await self.db.flush()
        return job

    async def _to_voucher(
        self,
        data: dict[str, Any],
        *,
        voucher_type: VoucherType,
        create_party: bool,
        create_items: bool,
    ):
        parties = PartyService(self.db, self.actor)
        items = ItemService(self.db, self.actor)

        party = None
        vendor = data.get("vendor_name")
        if vendor:
            matches = await parties.search_by_name(vendor, limit=1)
            if matches and matches[0][1] >= 0.75:
                party = matches[0][0]
            elif create_party:
                party, _ = await parties.resolve_or_create(
                    vendor,
                    party_type="supplier" if voucher_type is VoucherType.PURCHASE else "customer",
                    phone=data.get("vendor_phone"),
                )

        lines: list[VoucherLineInput] = []
        for raw in data.get("lines") or []:
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            qty = D(raw.get("qty") or 1)
            rate = money(raw.get("rate") or _derive_rate(raw, qty))

            item = None
            matched = await items.search_by_name(name, limit=1)
            if matched and matched[0][1] >= 0.8:
                item = matched[0][0]
            elif create_items:
                item, _ = await items.resolve_or_create(name, purchase_price=rate)

            lines.append(
                VoucherLineInput(
                    item_id=item.id if item else None,
                    item_name=item.name if item else name,
                    description=raw.get("description"),
                    hsn_code=raw.get("hsn_code"),
                    unit_label=raw.get("unit") or "Pcs",
                    qty=qty,
                    rate=rate,
                    tax_rate=money(raw["tax_rate"]) if raw.get("tax_rate") is not None else None,
                )
            )

        if not lines:
            raise BusinessRuleError("No line items could be read from this document.")

        # Most bills print one tax figure at the bottom and none per line, but the
        # voucher engine derives tax from the lines. Without this the saved bill
        # would total less than the paper one and nobody would know why.
        _apply_document_tax(lines, data)

        payment = None
        if data.get("paid"):
            from app.schemas.voucher import PaymentInline  # noqa: PLC0415

            payment = PaymentInline(
                amount=money(data["paid"]), mode=data.get("payment_mode") or "cash"
            )

        return await VoucherService(self.db, self.actor).create(
            VoucherCreate(
                voucher_type=voucher_type,
                party_id=party.id if party else None,
                party_name=party.name if party else vendor,
                reference_number=data.get("invoice_number"),
                voucher_date=parse_date(data.get("invoice_date"), date.today()),
                due_date=parse_date(data.get("due_date")),
                lines=lines,
                discount_value=money(data.get("discount") or 0),
                shipping_charge=money(data.get("shipping") or 0),
                notes=data.get("notes"),
                payment=payment,
                source="ocr",
            )
        )

    async def _to_expense(self, data: dict[str, Any]):
        total = money(data.get("total") or _sum_lines(data))
        if total <= 0:
            raise BusinessRuleError("No amount could be read from this receipt.")
        title = data.get("vendor_name") or (
            (data.get("lines") or [{}])[0].get("name") if data.get("lines") else None
        ) or "Scanned receipt"
        return await ExpenseService(self.db, self.actor).create(
            ExpenseCreate(
                title=str(title)[:240],
                amount=total,
                expense_date=parse_date(data.get("invoice_date"), date.today()),
                vendor_name=data.get("vendor_name"),
                payment_mode=data.get("payment_mode") or "cash",
                reference_number=data.get("invoice_number"),
                description=data.get("notes"),
                source="ocr",
            )
        )

    async def get(self, job_id: str) -> OcrJob:
        job = (
            await self.db.execute(
                select(OcrJob).where(
                    OcrJob.id == job_id, OcrJob.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise NotFoundError("Scan not found.", details={"id": job_id})
        return job

    async def recent(self, limit: int = 20) -> list[OcrJob]:
        rows = await self.db.execute(
            select(OcrJob)
            .where(OcrJob.business_id == self.business_id)
            .order_by(OcrJob.created_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())


def _parse_json(text: str) -> dict[str, Any] | None:
    import json  # noqa: PLC0415

    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Structured outputs make this rare, but a fenced block is a cheap recovery.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _apply_document_tax(lines: list[VoucherLineInput], data: dict[str, Any]) -> None:
    """Spread a document-level tax total back onto the lines.

    Only runs when the bill printed a tax amount but no per-line rates — if the
    document already breaks tax down per line, that is more precise and is left
    alone. The implied rate is rounded to two decimals, which lands exactly on
    the rates shops actually use (17, 18, 12, 5).
    """
    tax_amount = D(data.get("tax_amount") or 0)
    if tax_amount <= 0 or any(line.tax_rate for line in lines):
        return

    taxable = sum((D(line.qty) * D(line.rate) for line in lines), ZERO)
    if taxable <= 0:
        return

    rate = (tax_amount / taxable * 100).quantize(Decimal("0.01"))
    if rate <= 0 or rate > 100:
        return

    for line in lines:
        line.tax_rate = rate


def _warnings(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if D(data.get("confidence", 0)) < Decimal("0.6"):
        out.append("Low confidence — please check every field before saving.")
    for field in data.get("unreadable_fields") or []:
        out.append(f"Could not read: {field}")
    if not data.get("lines"):
        out.append("No line items were found.")
    if data.get("total") is not None:
        computed = _sum_lines(data)
        if computed and abs(D(data["total"]) - computed) > Decimal("1"):
            out.append(
                f"Line items add up to {computed}, but the printed total is {data['total']}."
            )
    if data.get("notes"):
        out.append(str(data["notes"]))
    return out


def _sum_lines(data: dict[str, Any]) -> Decimal:
    total = ZERO
    for line in data.get("lines") or []:
        if line.get("amount") is not None:
            total += D(line["amount"])
        elif line.get("qty") is not None and line.get("rate") is not None:
            total += D(line["qty"]) * D(line["rate"])
    return money(total)


def _derive_rate(line: dict[str, Any], qty: Decimal) -> Decimal:
    if line.get("amount") is not None and qty:
        return money(D(line["amount"]) / qty)
    return ZERO
