"""
Domain types for the Trade Promotion Deductions API.

Enumerations mirror the declared value sets of the PRD; the TypedDicts mirror
the persisted field sets. Per PRD section 2.4 almost every resource carries
`id`, `created_at`, `updated_at` and `version`; `VolumeFact` is the single
exception and carries only `id` and `created_at`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    """The six role names, spelled exactly as the PRD declares them."""

    TRADE_MARKETING_DIRECTOR = "TradeMarketingDirector"
    KEY_ACCOUNT_MANAGER = "KeyAccountManager"
    TRADE_FINANCE_ANALYST = "TradeFinanceAnalyst"
    DEDUCTION_SPECIALIST = "DeductionSpecialist"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    CUSTOMER_PORTAL_USER = "CustomerPortalUser"


ALL_ROLES = [r.value for r in UserRole]
INTERNAL_ROLES = [
    UserRole.TRADE_MARKETING_DIRECTOR.value,
    UserRole.KEY_ACCOUNT_MANAGER.value,
    UserRole.TRADE_FINANCE_ANALYST.value,
    UserRole.DEDUCTION_SPECIALIST.value,
    UserRole.COMPLIANCE_AUDITOR.value,
]


# ─── Enumerated value sets ────────────────────────────

class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class AccrualMethod(str, Enum):
    SHIPMENT = "SHIPMENT"
    CONSUMPTION = "CONSUMPTION"


class Channel(str, Enum):
    GROCERY = "GROCERY"
    MASS = "MASS"
    CLUB = "CLUB"
    DOLLAR = "DOLLAR"


class DeductionValidationPolicy(str, Enum):
    EVIDENCE_BASED = "EVIDENCE_BASED"
    AGREEMENT_CAP = "AGREEMENT_CAP"


class TradingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class AuditStatus(str, Enum):
    CLEAR = "CLEAR"
    AUDIT_IN_PROGRESS = "AUDIT_IN_PROGRESS"
    FINDINGS_OPEN = "FINDINGS_OPEN"


class EventType(str, Enum):
    SEASONAL = "SEASONAL"
    EVERYDAY = "EVERYDAY"
    NEW_ITEM = "NEW_ITEM"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class AllocationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PromotionLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    ANALYZED = "ANALYZED"
    WITHDRAWN = "WITHDRAWN"


class SpendStatus(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    OVERSPEND_WARNING = "OVERSPEND_WARNING"
    OVERSPENT = "OVERSPENT"


class PerformanceFlag(str, Enum):
    UNRATED = "UNRATED"
    UNDERPERFORMING = "UNDERPERFORMING"
    ON_TRACK = "ON_TRACK"


class TacticType(str, Enum):
    TPR = "TPR"
    DISPLAY = "DISPLAY"
    FEATURE = "FEATURE"


class TacticStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DocClass(str, Enum):
    COMMITMENT = "COMMITMENT"
    EVIDENCE = "EVIDENCE"


class DocType(str, Enum):
    SIGNED_LOI = "SIGNED_LOI"
    PORTAL_ACK = "PORTAL_ACK"
    SCAN_DATA = "SCAN_DATA"
    DISPLAY_PHOTO = "DISPLAY_PHOTO"
    AD_TEARSHEET = "AD_TEARSHEET"


class CoversTacticType(str, Enum):
    TPR = "TPR"
    DISPLAY = "DISPLAY"
    FEATURE = "FEATURE"
    ALL = "ALL"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class FactType(str, Enum):
    SHIPMENT = "SHIPMENT"
    CONSUMPTION = "CONSUMPTION"


class FactSource(str, Enum):
    EDI_852 = "EDI_852"
    EDI_856 = "EDI_856"
    MANUAL = "MANUAL"


class EntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"


class AccrualEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DeductionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHED = "MATCHED"
    VALIDATED = "VALIDATED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DisputeReasonCode(str, Enum):
    NO_AGREEMENT = "NO_AGREEMENT"
    NO_EVIDENCE = "NO_EVIDENCE"
    RATE_MISMATCH = "RATE_MISMATCH"
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_RETAILER = "AWAITING_RETAILER"
    ESCALATED = "ESCALATED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RetailerResponse(str, Enum):
    ACCEPT_CHARGEBACK = "ACCEPT_CHARGEBACK"
    PROVIDE_EVIDENCE = "PROVIDE_EVIDENCE"
    REFUSE = "REFUSE"


class BaselineMethod(str, Enum):
    TRAILING = "TRAILING"
    SEASONAL = "SEASONAL"


class DataStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ComplianceAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"


# ─── Entity shapes ────────────────────────────────────

class TradeProgram(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: int
    total_budget_amount: float
    accrual_method_default: str
    status: str
    allocated_amount: float
    unallocated_amount: float
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    list_price_per_case: float
    cogs_per_case: float
    unit_margin: float
    baseline_units_per_week: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    channel: str
    deduction_validation_policy: str
    trading_status: str
    audit_status: str
    compliance_penalty_points: int
    credit_hold_reason: Optional[str]
    open_deduction_amount: float
    write_off_ytd_amount: float
    created_at: str
    updated_at: str
    version: int


class BudgetAllocation(TypedDict, total=False):
    id: str
    program_id: str
    customer_id: str
    brand_id: str
    event_type: str
    planned_amount: float
    baseline_units: int
    planned_incremental_units: int
    status: str
    posture: str
    overspend_event_count: int
    committed_amount: float
    available_amount: float
    committed_units: int
    unreserved_units: int
    accrued_amount: float
    settled_amount: float
    at_risk_amount: float
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    allocation_id: str
    customer_id: str
    brand_id: str
    name: str
    window_start: str
    window_end: str
    accrual_method: str
    lifecycle_status: str
    revision_round: int
    approved_by_user_id: Optional[str]
    change_notes: Optional[str]
    withdraw_reason: Optional[str]
    commitment_verified: bool
    tactic_subtotal_amount: float
    allowance_rate: float
    off_invoice_allowance_amount: float
    planned_total_spend: float
    committed_units: int
    gross_accrued_amount: float
    reversed_accrual_amount: float
    consumed_deduction_amount: float
    accrued_balance: float
    recognized_spend_amount: float
    spend_ratio: float
    spend_status: str
    performance_flag: str
    created_at: str
    updated_at: str
    version: int


class PromotionTactic(TypedDict, total=False):
    id: str
    promotion_id: str
    tactic_type: str
    planned_units: int
    rate_per_case: Optional[float]
    fixed_fee: Optional[float]
    window_start: str
    window_end: str
    week_count: int
    line_planned_spend: float
    status: str
    effective_from_period: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailerDocument(TypedDict, total=False):
    id: str
    promotion_id: str
    doc_class: str
    doc_type: str
    covers_tactic_type: str
    received_at: str
    units_verified: int
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolumeFact(TypedDict, total=False):
    """Append-only journal row: no `updated_at` and no `version` (PRD 2.4)."""

    id: str
    customer_id: str
    brand_id: str
    fact_type: str
    period_start: str
    units: int
    source: str
    created_at: str


class AccrualEntry(TypedDict, total=False):
    id: str
    promotion_id: str
    entry_type: str
    status: str
    period_start: str
    method: str
    fact_units: int
    amount: float
    tactic_line_amounts: List[Dict[str, Any]]
    reverses_entry_id: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deduction(TypedDict, total=False):
    id: str
    customer_id: str
    promotion_id: Optional[str]
    claim_reference: str
    claimed_amount: float
    deduction_date: str
    supersedes_deduction_id: Optional[str]
    status: str
    validation_basis: Optional[str]
    entitled_amount: Optional[float]
    validated_amount: Optional[float]
    variance_amount: Optional[float]
    matched_by_user_id: Optional[str]
    validated_by_user_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    deduction_id: str
    reason_code: str
    disputed_amount: float
    status: str
    opened_at: str
    opened_by_user_id: str
    round_count: int
    aging_days: int
    packet_notes: Optional[str]
    retailer_response: Optional[str]
    recovered_amount: Optional[float]
    write_off_amount: Optional[float]
    write_off_reason: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostEventAnalysis(TypedDict, total=False):
    id: str
    promotion_id: str
    baseline_method: str
    data_status: str
    promo_consumption_units: int
    baseline_weekly_units: float
    baseline_units: float
    lift_units: float
    post_period_units: int
    cannibalization_units: float
    net_incremental_units: float
    incremental_gross_profit: float
    net_spend: float
    roi: Optional[float]
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    customer_id: str
    scope_start: str
    scope_end: str
    status: str
    findings_count: int
    recovery_claim_amount: float
    issued_at: Optional[str]
    auditor_user_id: str
    created_at: str
    updated_at: str
    version: int


class ActivationRunResult(TypedDict, total=False):
    run_at: str
    promotions_activated: List[str]
    promotions_ended: List[str]
    tactics_activated: List[str]
    tactics_completed: List[str]


class AgingRunResult(TypedDict, total=False):
    run_at: str
    disputes_scanned: int
    disputes_escalated: List[str]
    customers_penalized: List[str]
