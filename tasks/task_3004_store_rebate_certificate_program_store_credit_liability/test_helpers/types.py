"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STORE_ADMIN = "StoreAdmin"
    GUEST_SERVICE = "GuestService"
    FRAUD_ANALYST = "FraudAnalyst"
    FINANCE_ADMIN = "FinanceAdmin"
    CUSTOMER = "Customer"
    CONTRACTOR = "Contractor"


class RebateProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    RETAIL = "RETAIL"
    CONTRACTOR = "CONTRACTOR"


class CreditAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class JobPurchaseStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class ReceiptStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    FULLY_RETURNED = "FULLY_RETURNED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ExclusionReason(str, Enum):
    NO_PROGRAM_ITEM = "NO_PROGRAM_ITEM"
    EXCLUDED_CATEGORY = "EXCLUDED_CATEGORY"
    BELOW_MIN_QUANTITY = "BELOW_MIN_QUANTITY"
    FULLY_CERTIFICATE_TENDERED = "FULLY_CERTIFICATE_TENDERED"
    FULLY_RETURNED = "FULLY_RETURNED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    FULLY_REDEEMED = "FULLY_REDEEMED"
    EXPIRED = "EXPIRED"
    REISSUED = "REISSUED"
    VOIDED = "VOIDED"


class FraudHold(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    RELEASED = "RELEASED"


class LedgerEntryType(str, Enum):
    ISSUANCE_ACCRUAL = "ISSUANCE_ACCRUAL"
    REDEMPTION = "REDEMPTION"
    REVERSAL_DEBIT = "REVERSAL_DEBIT"
    BREAKAGE_EXPIRY = "BREAKAGE_EXPIRY"
    REISSUE_CREDIT = "REISSUE_CREDIT"


class FraudFlagType(str, Enum):
    SPLIT_TRANSACTION = "SPLIT_TRANSACTION"
    DUPLICATE_RECEIPT = "DUPLICATE_RECEIPT"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class BreakageRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class TenderType(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    GIFT_CARD = "GIFT_CARD"
    STORE_CREDIT_CERTIFICATE = "STORE_CREDIT_CERTIFICATE"


class BonusTier(str, Enum):
    NONE = "NONE"
    PRO = "PRO"
    PRO_PLUS = "PRO_PLUS"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Store(TypedDict):
    id: str
    store_code: str
    submission_window_days: int
    certificate_validity_months: int
    expected_breakage_rate: float
    split_txn_window_hours: int
    split_txn_min_receipts: int
    outstanding_liability_cents: int
    net_liability_cents: int
    accrued_breakage_income_cents: int
    liability_epoch: int
    created_at: str
    updated_at: str
    version: int


class RebateProgram(TypedDict):
    id: str
    name: str
    week_start_date: str
    week_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramItem(TypedDict):
    id: str
    program_id: str
    sku: str
    rebate_pct: float
    excluded_categories: List[str]
    min_quantity: int
    per_receipt_cap_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CreditAccount(TypedDict):
    id: str
    owner_name: str
    account_type: str
    status: str
    credit_balance_cents: int
    pending_award_cents: int
    lifetime_rebate_cents: int
    created_at: str
    updated_at: str
    version: int


class JobPurchase(TypedDict):
    id: str
    contractor_account_id: str
    job_reference: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    store_id: str
    receipt_number: str
    account_id: str
    job_purchase_id: Optional[str]
    purchase_at: str
    status: str
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class TenderSplit(TypedDict):
    tender_type: str
    amount_cents: int


class ReceiptLine(TypedDict):
    # line-level sub-resource: only id + created_at (no updated_at, no version)
    id: str
    receipt_id: str
    line_number: int
    sku: str
    category: str
    quantity: int
    unit_price_cents: int
    returned_quantity: int
    tender_splits: List[TenderSplit]
    certificate_tendered_cents: int
    created_at: str


class Return(TypedDict):
    id: str
    receipt_id: str
    lines: List[dict]
    processed_at: str
    reversal_entry_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class RebateSubmission(TypedDict):
    id: str
    account_id: str
    receipt_id: str
    status: str
    provisional_award_cents: int
    award_cents: Optional[int]
    rejection_reason: Optional[str]
    submitted_at: str
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int


class SubmissionLine(TypedDict):
    # line-level sub-resource: only id + created_at (no updated_at, no version)
    id: str
    submission_id: str
    receipt_line_id: str
    program_item_id: Optional[str]
    eligible_base_cents: int
    awarded_cents: int
    exclusion_reason: Optional[str]
    created_at: str


class RebateCertificate(TypedDict):
    id: str
    account_id: str
    submission_id: Optional[str]
    store_id: str
    issued_amount_cents: int
    remaining_balance_cents: int
    status: str
    fraud_hold: str
    issued_at: str
    expires_at: str
    reissued_from_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict):
    # append-only record: only id + created_at (no updated_at, no version)
    id: str
    account_id: str
    certificate_id: str
    entry_type: str
    amount_cents: int
    liability_epoch: int
    created_note: str
    created_at: str


class FraudFlag(TypedDict):
    id: str
    account_id: str
    flag_type: str
    status: str
    receipt_ids: List[str]
    detail: str
    created_at: str
    updated_at: str
    version: int


class BreakageRun(TypedDict):
    id: str
    store_id: str
    status: str
    run_at: str
    expired_count: int
    breakage_recognized_cents: int
    epoch: int
    created_at: str
    updated_at: str
    version: int


class ContractorSummary(TypedDict):
    account_job_total_cents: int
    bonus_tier: str
    bonus_cents: int
    jobs: List[dict]
