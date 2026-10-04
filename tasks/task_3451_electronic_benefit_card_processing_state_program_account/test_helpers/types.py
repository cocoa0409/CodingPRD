"""Domain types: entity TypedDicts, status enums, and the role enum (PRD §2–§3).

Every entity except LedgerEntry carries the common fields `id`, `created_at`,
`updated_at`, and `version` (PRD §2.5). LedgerEntry is append-only and carries
only `id` and `created_at` — `updated_at` and `version` are absent (PRD §2.5),
so its TypedDict omits them.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# --- Roles (PRD §2.1) ---------------------------------------------------------
class UserRole(str, Enum):
    STATE_ADMIN = "StateAdmin"
    CARDHOLDER_SERVICES = "CardholderServices"
    CARDHOLDER = "Cardholder"
    RETAILER_SYSTEM = "RetailerSystem"


# --- Status / type enums (PRD §3) ---------------------------------------------
class ContractStatus(str, Enum):
    CONFIGURING = "CONFIGURING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProgramType(str, Enum):
    FOOD = "FOOD"
    CASH = "CASH"
    DISASTER = "DISASTER"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class ItemRestrictionMode(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class RetailerStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"


class PurseStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    POST_CREDIT = "POST_CREDIT"
    PURCHASE_DEBIT = "PURCHASE_DEBIT"
    WITHDRAWAL_DEBIT = "WITHDRAWAL_DEBIT"
    FEE_DEBIT = "FEE_DEBIT"
    VOID_CREDIT = "VOID_CREDIT"
    FORFEIT_DEBIT = "FORFEIT_DEBIT"
    EXPIRY_DEBIT = "EXPIRY_DEBIT"
    EXPUNGE_DEBIT = "EXPUNGE_DEBIT"
    PROVISIONAL_CREDIT = "PROVISIONAL_CREDIT"
    PROVISIONAL_REVERSAL_DEBIT = "PROVISIONAL_REVERSAL_DEBIT"
    CLAIM_CREDIT = "CLAIM_CREDIT"
    CLAIM_REVERSAL_DEBIT = "CLAIM_REVERSAL_DEBIT"


LEDGER_CREDIT_TYPES = (
    LedgerEntryType.POST_CREDIT.value,
    LedgerEntryType.VOID_CREDIT.value,
    LedgerEntryType.PROVISIONAL_CREDIT.value,
    LedgerEntryType.CLAIM_CREDIT.value,
)

LEDGER_DEBIT_TYPES = (
    LedgerEntryType.PURCHASE_DEBIT.value,
    LedgerEntryType.WITHDRAWAL_DEBIT.value,
    LedgerEntryType.FEE_DEBIT.value,
    LedgerEntryType.FORFEIT_DEBIT.value,
    LedgerEntryType.EXPIRY_DEBIT.value,
    LedgerEntryType.EXPUNGE_DEBIT.value,
    LedgerEntryType.PROVISIONAL_REVERSAL_DEBIT.value,
    LedgerEntryType.CLAIM_REVERSAL_DEBIT.value,
)


class PostingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AVAILABLE = "AVAILABLE"
    EXPUNGED = "EXPUNGED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


class CardStatus(str, Enum):
    ISSUED = "ISSUED"
    MAILED = "MAILED"
    ACTIVE = "ACTIVE"
    PIN_LOCKED = "PIN_LOCKED"
    REPLACED = "REPLACED"
    DEACTIVATED = "DEACTIVATED"


class AuthorizationType(str, Enum):
    PURCHASE = "PURCHASE"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"


class TxnStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    VOIDED = "VOIDED"
    SETTLED = "SETTLED"


class InvestigationStatus(str, Enum):
    FILED = "FILED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class CreditStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class BatchStatus(str, Enum):
    CUTOFF = "CUTOFF"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"


class DisputeType(str, Enum):
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    RETAILER_DISPUTE = "RETAILER_DISPUTE"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class DeliveryType(str, Enum):
    DAILY_TRANSACTION_FILE = "DAILY_TRANSACTION_FILE"
    MONTHLY_INTEGRITY_REPORT = "MONTHLY_INTEGRITY_REPORT"


class DeliveryStatus(str, Enum):
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"


# --- Entity TypedDicts --------------------------------------------------------
# All entities except LedgerEntry carry id/created_at/updated_at/version
# (PRD §2.5). Optional[...] marks fields the PRD documents as nullable.

class StateContract(TypedDict, total=False):
    id: str
    state_code: str
    contract_status: str
    default_posting_modulus: int
    default_availability_hour_utc: int
    default_expungement_inactivity_days: int
    expungement_notice_lead_days: int
    default_disaster_expiry_days: int
    default_replacement_fee_cents: int
    free_replacements_per_365d: int
    pin_max_failures: int
    claim_window_days: int
    provisional_credit_delay_days: int
    provisional_credit_cap_cents: int
    skimming_suspend_threshold: int
    dispute_window_days: int
    acquirer_fee_basis_points: int
    cash_withdrawal_daily_limit_cents: int
    cash_withdrawal_multiple_cents: int
    settlement_cutoff_hour_utc: int
    card_mail_delay_hours: int
    created_at: str
    updated_at: str
    version: int


class BenefitProgram(TypedDict, total=False):
    id: str
    contract_id: str
    program_type: str
    program_status: str
    item_restriction_mode: str
    posting_modulus: Optional[int]
    availability_hour_utc: Optional[int]
    expungement_inactivity_days: Optional[int]
    disaster_expiry_days: Optional[int]
    replacement_fee_cents: Optional[int]
    disaster_window_start: Optional[str]
    disaster_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict, total=False):
    id: str
    contract_id: str
    retailer_name: str
    acquirer_reference: str
    retailer_status: str
    skimming_incident_count: int
    created_at: str
    updated_at: str
    version: int


class RetailerItem(TypedDict, total=False):
    id: str
    retailer_id: str
    upc: str
    food_eligible: bool
    effective_from: str
    effective_to: Optional[str]
    item_status: str
    created_at: str
    updated_at: str
    version: int


class CaseAccount(TypedDict, total=False):
    id: str
    contract_id: str
    case_identifier: str
    head_of_household_name: str
    account_status: str
    replacements_in_window: int
    created_at: str
    updated_at: str
    version: int


class Purse(TypedDict, total=False):
    id: str
    case_account_id: str
    program_id: str
    purse_status: str
    last_activity_at: Optional[str]
    expungement_notice_sent_at: Optional[str]
    ledger_balance_cents: int
    spendable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only (PRD §2.5): id + created_at only; NO updated_at, NO version.
    id: str
    created_at: str
    purse_id: str
    entry_type: str
    amount_cents: int
    posting_id: Optional[str]
    reference_id: Optional[str]
    memo: Optional[str]


class BenefitPosting(TypedDict, total=False):
    id: str
    purse_id: str
    benefit_month: str
    amount_cents: int
    prorated: bool
    scheduled_date: str
    available_at: str
    posting_status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict, total=False):
    id: str
    case_account_id: str
    pan_token: str
    card_status: str
    pin_secret: Optional[str]      # masked '****' in responses (PRD §3.6)
    pin_fail_count: int
    replacement_of_card_id: Optional[str]
    fee_charged_cents: Optional[int]
    fee_waived: bool
    mailed_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseItem(TypedDict, total=False):
    upc: str
    quantity: int
    unit_price_cents: int


class PurchaseTransaction(TypedDict, total=False):
    id: str
    retailer_id: str
    case_account_id: str
    card_id: str
    authorization_type: str
    items: Optional[List[PurchaseItem]]
    withdrawal_amount_cents: Optional[int]
    food_charge_cents: int
    cash_charge_cents: int
    disaster_charge_cents: int
    total_cents: int
    exception_flag_count: int
    txn_status: str
    batch_id: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SkimmingClaim(TypedDict, total=False):
    id: str
    case_account_id: str
    card_id: str
    authorization_ids: List[str]
    claimed_amount_cents: int
    incident_description: str
    freeze_purse: bool
    investigation_status: str
    credit_status: str
    provisional_credit_cents: int
    provisional_credited_at: Optional[str]
    substantiated_amount_cents: Optional[int]
    filed_by_user_id: str
    filed_by_role: str
    decided_by_user_id: Optional[str]
    investigated_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    contract_id: str
    acquirer_reference: str
    settlement_date: str
    cutoff_at: str
    batch_status: str
    gross_settled_cents: int
    txn_count: int
    acquirer_fee_cents: int
    adjustment_total_cents: int
    net_position_cents: int
    settled_authorization_ids: List[str]
    actual_settled_cents: Optional[int]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementDispute(TypedDict, total=False):
    id: str
    settlement_batch_id: str
    dispute_type: str
    retailer_id: Optional[str]
    dispute_status: str
    disputed_amount_cents: int
    adjustment_cents: Optional[int]
    reason: str
    filed_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataDelivery(TypedDict, total=False):
    id: str
    contract_id: str
    delivery_type: str
    period: str
    delivery_status: str
    txn_count: Optional[int]
    settled_food_cents: Optional[int]
    settled_cash_cents: Optional[int]
    expunged_cents: Optional[int]
    expired_cents: Optional[int]
    substantiated_claims_count: Optional[int]
    provisional_credits_outstanding_cents: Optional[int]
    retailer_suspensions_count: Optional[int]
    lenient_exceptions_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


__all__ = [name for name in dir() if not name.startswith("_") and name not in ("Any", "List", "Optional", "TypedDict", "Enum")]
