"""Model registry. Importing this module registers every table on `Base.metadata`."""

from app.models.ai import (
    AiConversation, AiInsight, AiMessage, AiToolCall, AiUsage, OcrJob,
)
from app.models.base import Base, gen_uuid, utcnow
from app.models.business import Business, BusinessMember, BusinessSettings
from app.models.enums import (
    BusinessType, DiscountType, ItemType, MessageRole, NotificationChannel, OcrStatus,
    PartyType, PaymentDirection, PaymentMode, SerialStatus, StockMovement, SyncOperation,
    TaxType, VoucherStatus, VoucherType,
)
from app.models.expense import Expense, ExpenseCategory, TaxRate
from app.models.finance import AccountTransfer, Loan, LoanPayment
from app.models.item import (
    Godown, GodownStock, Item, ItemBatch, ItemCategory, ItemSerial, StockLedgerEntry, Unit,
)
from app.models.party import Party, PartyGroup
from app.models.loyalty import LoyaltyEntry, LoyaltyProgram
from app.models.pricing import DiscountScheme, PriceList, PriceListEntry
from app.models.recurring import RecurringInvoice
from app.models.payment import Account, Payment, PaymentAllocation
from app.models.system import (
    Attachment, AuditLog, ChangeLog, Integration, MessageLog, Notification,
    NumberSequence, SyncState,
)
from app.models.user import OtpChallenge, User, UserSession
from app.models.voucher import Voucher, VoucherLine

__all__ = [
    "Base", "gen_uuid", "utcnow",
    # tenancy
    "Business", "BusinessMember", "BusinessSettings",
    # identity
    "User", "UserSession", "OtpChallenge",
    # masters
    "Party", "PartyGroup",
    "Item", "ItemCategory", "ItemBatch", "ItemSerial", "Unit", "Godown", "GodownStock",
    "StockLedgerEntry",
    "TaxRate", "ExpenseCategory", "Account",
    "PriceList", "PriceListEntry", "DiscountScheme",
    "LoyaltyProgram", "LoyaltyEntry",
    # transactions
    "Voucher", "VoucherLine", "Payment", "PaymentAllocation", "Expense",
    "AccountTransfer", "Loan", "LoanPayment", "RecurringInvoice",
    # ai
    "AiConversation", "AiMessage", "AiToolCall", "AiUsage", "AiInsight", "OcrJob",
    # system
    "AuditLog", "ChangeLog", "SyncState", "NumberSequence", "Attachment",
    "Notification", "Integration", "MessageLog",
    # enums
    "VoucherType", "VoucherStatus", "PartyType", "PaymentDirection", "PaymentMode",
    "TaxType", "StockMovement", "ItemType", "SerialStatus", "DiscountType", "BusinessType",
    "MessageRole", "OcrStatus", "NotificationChannel", "SyncOperation",
]


# Entity name → model, used by the sync engine and the AI tool layer.
SYNCABLE_MODELS: dict[str, type] = {
    "party": Party,
    "party_group": PartyGroup,
    "item": Item,
    "item_category": ItemCategory,
    "unit": Unit,
    "godown": Godown,
    "item_batch": ItemBatch,
    "item_serial": ItemSerial,
    "voucher": Voucher,
    "payment": Payment,
    "expense": Expense,
    "expense_category": ExpenseCategory,
    "tax_rate": TaxRate,
    "account": Account,
    "price_list": PriceList,
    "discount_scheme": DiscountScheme,
    "recurring_invoice": RecurringInvoice,
}
