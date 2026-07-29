"""Domain enums. Stored as strings so migrations stay painless on Postgres."""

from __future__ import annotations

from enum import StrEnum


class VoucherType(StrEnum):
    """Every trade document lives in one table, discriminated by this."""

    SALE = "sale"                       # tax invoice / bill
    PURCHASE = "purchase"               # supplier bill
    SALE_RETURN = "sale_return"         # credit note
    PURCHASE_RETURN = "purchase_return" # debit note
    QUOTATION = "quotation"             # estimate — no stock, no ledger
    PROFORMA = "proforma"
    DELIVERY_CHALLAN = "delivery_challan"
    SALE_ORDER = "sale_order"
    PURCHASE_ORDER = "purchase_order"

    @property
    def affects_stock(self) -> bool:
        return self in _STOCK_AFFECTING

    @property
    def affects_ledger(self) -> bool:
        return self in _LEDGER_AFFECTING

    @property
    def is_outward(self) -> bool:
        """True when goods/value leave the business (sales side)."""
        return self in {VoucherType.SALE, VoucherType.PURCHASE_RETURN, VoucherType.DELIVERY_CHALLAN}

    @property
    def party_kind(self) -> str:
        return "supplier" if self in {
            VoucherType.PURCHASE, VoucherType.PURCHASE_RETURN, VoucherType.PURCHASE_ORDER
        } else "customer"


_STOCK_AFFECTING = {
    VoucherType.SALE, VoucherType.PURCHASE,
    VoucherType.SALE_RETURN, VoucherType.PURCHASE_RETURN,
    VoucherType.DELIVERY_CHALLAN,
}
_LEDGER_AFFECTING = {
    VoucherType.SALE, VoucherType.PURCHASE,
    VoucherType.SALE_RETURN, VoucherType.PURCHASE_RETURN,
}


class VoucherStatus(StrEnum):
    DRAFT = "draft"
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    CONVERTED = "converted"   # quotation → invoice


class PartyType(StrEnum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    BOTH = "both"


class PaymentDirection(StrEnum):
    IN = "in"     # money received from a customer
    OUT = "out"   # money paid to a supplier / refund


class PaymentMode(StrEnum):
    CASH = "cash"
    BANK = "bank"
    UPI = "upi"
    CARD = "card"
    CHEQUE = "cheque"
    NEFT = "neft"
    EASYPAISA = "easypaisa"
    JAZZCASH = "jazzcash"
    OTHER = "other"


class TaxType(StrEnum):
    NONE = "none"
    GST = "gst"          # India: CGST+SGST intra-state, IGST inter-state
    VAT = "vat"
    SALES_TAX = "sales_tax"   # Pakistan FBR
    EXEMPT = "exempt"


class StockMovement(StrEnum):
    IN = "in"
    OUT = "out"
    ADJUSTMENT = "adjustment"
    OPENING = "opening"
    TRANSFER = "transfer"


class ItemType(StrEnum):
    PRODUCT = "product"
    SERVICE = "service"


class DiscountType(StrEnum):
    PERCENT = "percent"
    AMOUNT = "amount"


class BusinessType(StrEnum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    MANUFACTURING = "manufacturing"
    SERVICE = "service"
    DISTRIBUTOR = "distributor"
    RESTAURANT = "restaurant"
    PHARMACY = "pharmacy"
    OTHER = "other"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class OcrStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    APPLIED = "applied"     # user accepted the draft and it became a voucher


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    PUSH = "push"


class SyncOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
