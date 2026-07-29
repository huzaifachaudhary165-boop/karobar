"""Model registry. Importing this module registers every table on `Base.metadata`."""

from app.models.ai import (
    AiConversation, AiInsight, AiMessage, AiToolCall, AiUsage, OcrJob,
)
from app.models.base import Base, gen_uuid, utcnow
from app.models.business import Business, BusinessMember, BusinessSettings
from app.models.enums import (
    BusinessType, DiscountType, ItemType, MessageRole, NotificationChannel, OcrStatus,
    PartyType, PaymentDirection, PaymentMode, StockMovement, SyncOperation, TaxType,
    VoucherStatus, VoucherType,
)
from app.models.expense import Expense, ExpenseCategory, TaxRate
from app.models.item import Godown, Item, ItemBatch, ItemCategory, StockLedgerEntry, Unit
from app.models.party import Party, PartyGroup
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
    "Item", "ItemCategory", "ItemBatch", "Unit", "Godown", "StockLedgerEntry",
    "TaxRate", "ExpenseCategory", "Account",
    # transactions
    "Voucher", "VoucherLine", "Payment", "PaymentAllocation", "Expense",
    # ai
    "AiConversation", "AiMessage", "AiToolCall", "AiUsage", "AiInsight", "OcrJob",
    # system
    "AuditLog", "ChangeLog", "SyncState", "NumberSequence", "Attachment",
    "Notification", "Integration", "MessageLog",
    # enums
    "VoucherType", "VoucherStatus", "PartyType", "PaymentDirection", "PaymentMode",
    "TaxType", "StockMovement", "ItemType", "DiscountType", "BusinessType",
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
    "voucher": Voucher,
    "payment": Payment,
    "expense": Expense,
    "expense_category": ExpenseCategory,
    "tax_rate": TaxRate,
    "account": Account,
}
