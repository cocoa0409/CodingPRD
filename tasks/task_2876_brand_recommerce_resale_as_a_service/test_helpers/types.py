"""Domain types for the brand recommerce resale platform.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them. Entities that the PRD describes as append-only carry only ``id``
and ``created_at`` and therefore omit ``updated_at`` / ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_AGENT = "IntakeAgent"
    AUTHENTICATOR = "Authenticator"
    REFURB_TECHNICIAN = "RefurbTechnician"
    MERCHANDISING_MANAGER = "MerchandisingManager"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------
class ProductCategory(str, Enum):
    FOOTWEAR = "FOOTWEAR"
    OUTERWEAR = "OUTERWEAR"
    BAG = "BAG"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    SALVAGE = "SALVAGE"


class IntakeChannel(str, Enum):
    MAIL_IN = "MAIL_IN"
    IN_STORE = "IN_STORE"


class ChannelType(str, Enum):
    FULL_PRICE_DTC = "FULL_PRICE_DTC"
    RESALE_MARKETPLACE = "RESALE_MARKETPLACE"
    OUTLET = "OUTLET"


class Assortment(str, Enum):
    NEW_ONLY = "NEW_ONLY"
    RESALE_ONLY = "RESALE_ONLY"
    BOTH = "BOTH"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"


class OwnershipTreatment(str, Enum):
    OWNED_INVENTORY = "OWNED_INVENTORY"
    CONSIGNED = "CONSIGNED"


class AuthenticityResult(str, Enum):
    PENDING = "PENDING"
    GENUINE = "GENUINE"
    COUNTERFEIT = "COUNTERFEIT"
    INCONCLUSIVE = "INCONCLUSIVE"


class TaskType(str, Enum):
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    REPACKAGING = "REPACKAGING"


class BayType(str, Enum):
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    REPACKAGING = "REPACKAGING"


class ReturnReasonType(str, Enum):
    NONE = "NONE"
    BUYER_REMORSE = "BUYER_REMORSE"
    WARRANTY_DEFECT = "WARRANTY_DEFECT"


class ReturnResolution(str, Enum):
    REFUND = "REFUND"
    REPLACE = "REPLACE"
    DENY = "DENY"


class QcDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SALVAGE = "SALVAGE"


class DispositionDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class LedgerEntryType(str, Enum):
    ISSUE = "ISSUE"
    REDEEM = "REDEEM"
    RELEASE = "RELEASE"
    EXPIRE = "EXPIRE"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StoreLocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RefurbBayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ChannelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    AUTHENTICATED = "AUTHENTICATED"
    APPEALED = "APPEALED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CreditGrantStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class ResaleUnitLifecycleState(str, Enum):
    INTAKE = "INTAKE"
    IN_REFURB = "IN_REFURB"
    READY = "READY"
    LISTED = "LISTED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    SALVAGED = "SALVAGED"


class ResaleUnitAccountingState(str, Enum):
    UNCAPITALIZED = "UNCAPITALIZED"
    CAPITALIZED = "CAPITALIZED"
    WRITTEN_DOWN = "WRITTEN_DOWN"
    EXPENSED = "EXPENSED"


class RefurbOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    QC_PENDING = "QC_PENDING"
    QC_FAILED = "QC_FAILED"
    COMPLETED = "COMPLETED"
    SALVAGED = "SALVAGED"
    SUPERSEDED = "SUPERSEDED"


class MarkdownCampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ResaleOrderStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    REPLACED = "REPLACED"


class DiversionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_tier: str
    status: str
    credit_balance_minor: int
    diverted_grams_total: int
    created_at: str
    updated_at: str
    version: int


class GradePolicy(TypedDict):
    id: str
    product_category: str
    condition_grade: str
    base_credit_pct_bp: int
    resale_price_pct_bp: int
    refurb_budget_cap_pct_bp: int
    restock_fee_pct_bp: int
    warranty_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditPolicy(TypedDict):
    id: str
    code: str
    expiry_days: int
    mail_in_bonus_pct_bp: int
    max_redemption_pct_bp: int
    min_cash_remainder_minor: int
    eligible_assortment: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreLocation(TypedDict):
    id: str
    code: str
    region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RefurbBay(TypedDict):
    id: str
    store_location_id: str
    code: str
    bay_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    code: str
    channel_type: str
    allowed_assortment: str
    max_resale_price_ratio_bp: int
    region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    store_location_id: Optional[str]
    channel: str
    product_category: str
    declared_grade: str
    msrp_minor: int
    item_mass_grams: int
    status: str
    authenticity_result: str
    assessed_grade: Optional[str]
    graded_by_user_id: Optional[str]
    appeal_count: int
    appraised_credit_minor: int
    receive_deadline_at: str
    received_at: Optional[str]
    accepted_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditGrant(TypedDict):
    id: str
    customer_id: str
    trade_in_id: str
    credit_policy_id: str
    credit_policy_version: int
    issued_amount_minor: int
    remaining_minor: int
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditLedgerEntry(TypedDict):
    """Append-only ledger row: the PRD gives it an id and a created_at only."""

    id: str
    credit_grant_id: str
    customer_id: str
    entry_type: str
    amount_minor: int
    balance_after_minor: int
    resale_order_id: Optional[str]
    occurred_at: str
    created_at: str


class ResaleUnit(TypedDict):
    id: str
    trade_in_id: str
    product_category: str
    condition_grade: str
    mass_grams: int
    reference_msrp_minor: int
    ownership_treatment: str
    lifecycle_state: str
    accounting_state: str
    capitalized_cost_minor: int
    listed_channel_id: Optional[str]
    list_price_minor: Optional[int]
    current_price_minor: Optional[int]
    markdown_step_count: int
    listed_at: Optional[str]
    aged_days: int
    replacement_for_unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefurbOrder(TypedDict):
    id: str
    resale_unit_id: str
    refurb_bay_id: str
    window_start_at: str
    window_end_at: str
    status: str
    performed_by_user_id: Optional[str]
    qc_by_user_id: Optional[str]
    rework_count: int
    logged_cost_minor: int
    viability_ratio_bp: int
    viability_override_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefurbTask(TypedDict):
    """Append-only effort line: the PRD gives it an id and a created_at only."""

    id: str
    refurb_order_id: str
    sequence_no: int
    task_type: str
    labor_minutes: int
    parts_cost_minor: int
    cost_minor: int
    logged_by_user_id: str
    created_at: str


class MarkdownCampaign(TypedDict):
    id: str
    channel_id: str
    product_category: str
    window_start_at: str
    window_end_at: str
    cadence_days: int
    step_bp: int
    floor_pct_bp: int
    status: str
    run_count: int
    last_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResaleOrder(TypedDict):
    id: str
    customer_id: str
    channel_id: str
    resale_unit_id: str
    gross_price_minor: int
    channel_fee_minor: int
    order_total_minor: int
    credit_applied_minor: int
    cash_due_minor: int
    status: str
    reason_type: str
    fulfilled_at: Optional[str]
    warranty_expires_at: Optional[str]
    return_requested_at: Optional[str]
    restock_fee_minor: int
    refund_cash_minor: int
    refund_credit_minor: int
    created_at: str
    updated_at: str
    version: int


class DiversionReport(TypedDict):
    id: str
    period_start_at: str
    period_end_at: str
    supersedes_report_id: Optional[str]
    units_diverted_count: int
    diverted_grams: int
    salvage_grams: int
    landfill_diversion_rate_bp: int
    credit_liability_minor: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
