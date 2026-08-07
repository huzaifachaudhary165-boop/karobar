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

# What each document is allowed to become.
#
# A promise turns into a transaction, and only ever on its own side of the
# trade. Without this a purchase order could be converted into a sale invoice —
# billing the shop's own supplier as if they were a customer, at the shop's own
# buying prices. The default target was SALE, so that was one careless tap away.
CONVERTIBLE_TO: dict[VoucherType, frozenset[VoucherType]] = {
    VoucherType.QUOTATION: frozenset({
        VoucherType.SALE, VoucherType.PROFORMA, VoucherType.SALE_ORDER,
        VoucherType.DELIVERY_CHALLAN,
    }),
    VoucherType.PROFORMA: frozenset({
        VoucherType.SALE, VoucherType.SALE_ORDER, VoucherType.DELIVERY_CHALLAN,
    }),
    VoucherType.SALE_ORDER: frozenset({
        VoucherType.SALE, VoucherType.DELIVERY_CHALLAN,
    }),
    VoucherType.DELIVERY_CHALLAN: frozenset({VoucherType.SALE}),
    VoucherType.PURCHASE_ORDER: frozenset({VoucherType.PURCHASE}),
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


class AccountType(StrEnum):
    CASH = "cash"
    BANK = "bank"
    WALLET = "wallet"      # easypaisa / jazzcash / paytm
    CREDIT_CARD = "credit_card"


class ChequeStatus(StrEnum):
    """A cheque is a promise, not money, until the bank says otherwise."""

    PENDING = "pending"      # written or received, not yet presented
    DEPOSITED = "deposited"  # handed to the bank, still clearing
    CLEARED = "cleared"      # the money actually moved
    BOUNCED = "bounced"      # returned unpaid
    CANCELLED = "cancelled"


class LoanType(StrEnum):
    BANK = "bank"
    PERSONAL = "personal"     # from a person, often interest-free
    VEHICLE = "vehicle"
    GOLD = "gold"
    BUSINESS = "business"
    OTHER = "other"


class InterestType(StrEnum):
    """How the interest is worked out — the two answers give very different totals."""

    FLAT = "flat"          # charged on the original amount for the whole term
    REDUCING = "reducing"  # charged on what is still owed, so it falls each month
    NONE = "none"          # interest-free, common for family and committee loans


class LoanStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    DEFAULTED = "defaulted"


class SerialStatus(StrEnum):
    """Where one individually-numbered unit currently is."""

    IN_STOCK = "in_stock"
    SOLD = "sold"
    RETURNED = "returned"   # came back from a customer, sellable again
    DAMAGED = "damaged"


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
