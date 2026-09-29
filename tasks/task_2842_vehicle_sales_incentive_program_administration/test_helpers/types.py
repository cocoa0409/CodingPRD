"""Domain types for the Vehicle Sales Incentive Program Administration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_DESIGNER = "ProgramDesigner"
    INCENTIVE_CONTROLLER = "IncentiveController"
    FIELD_SALES_MANAGER = "FieldSalesManager"
    CLAIMS_AUDITOR = "ClaimsAuditor"
    DEALER = "Dealer"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class IncentiveType(str, Enum):
    CUSTOMER_CASH = "CUSTOMER_CASH"
    FINANCE_SUBVENTION = "FINANCE_SUBVENTION"
    LEASE_SUPPORT = "LEASE_SUPPORT"
    DEALER_STAIR_STEP = "DEALER_STAIR_STEP"


class TierBonusMode(str, Enum):
    MARGINAL = "MARGINAL"
    FULL_VOLUME = "FULL_VOLUME"


class AccrualMethod(str, Enum):
    UNIT_BASED = "UNIT_BASED"
    TAKE_RATE_BASED = "TAKE_RATE_BASED"


class StackMode(str, Enum):
    FORBIDDEN = "FORBIDDEN"
    CAPPED_TOTAL = "CAPPED_TOTAL"
    ALLOWED = "ALLOWED"


class DealType(str, Enum):
    CASH = "CASH"
    FINANCE = "FINANCE"
    LEASE = "LEASE"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ObjectiveStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PROTESTED = "PROTESTED"
    REVISED = "REVISED"
    FINAL = "FINAL"
    VOID = "VOID"


class ProtestStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class ProtestResolution(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class DeliveryStatus(str, Enum):
    REPORTED = "REPORTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    UNWOUND = "UNWOUND"


class ClaimValidationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    CHARGED_BACK = "CHARGED_BACK"


class ClaimType(str, Enum):
    UNIT_INCENTIVE = "UNIT_INCENTIVE"
    STAIR_STEP_BONUS = "STAIR_STEP_BONUS"


class RateBasis(str, Enum):
    AS_SOLD_SNAPSHOT = "AS_SOLD_SNAPSHOT"
    REPRICED_CURRENT = "REPRICED_CURRENT"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ChargebackReason(str, Enum):
    UNWOUND_DEAL = "UNWOUND_DEAL"
    BACK_DATED_SALE = "BACK_DATED_SALE"
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"
    OBJECTIVE_REVISED = "OBJECTIVE_REVISED"
    REPRICING_ADJUSTMENT = "REPRICING_ADJUSTMENT"


class AccrualEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"


class RepricingMode(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    RETROACTIVE_TO_MONTH_START = "RETROACTIVE_TO_MONTH_START"


# --- Entity shapes -----------------------------------------------------------
# Resources listed in PRD §2.4 as carrying updated_at and version.


class IncentiveProgram(TypedDict):
    id: str
    program_code: str
    name: str
    incentive_type: str
    status: str
    effective_from: str
    effective_to: str
    per_unit_amount_cents: int
    apr_buydown_bps: int
    residual_support_bps: int
    projected_take_rate_bps: int
    budget_cents: int
    stack_group: str
    stack_cap_cents: int
    priority_rank: int
    tier_schedule: List[dict]
    tier_bonus_mode: str
    accrual_method: str
    supersedes_program_id: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    committed_cents: int
    paid_cents: int
    accrued_budget_cents: int
    claimed_units: int
    per_unit_spend_cents: int
    residual_impact_bps: int
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    dealer_code: str
    name: str
    region_code: str
    status: str
    historical_volume_units: int
    market_opportunity_bps: int
    paid_cents: int
    open_chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class DealerObjective(TypedDict):
    id: str
    program_id: str
    dealer_id: str
    status: str
    basis_units: int
    stretch_bps: int
    objective_units: int
    achieved_units: int
    attainment_bps: int
    tier_attained: int
    payout_cents: int
    paid_payout_cents: int
    protest_round: int
    created_at: str
    updated_at: str
    version: int


class ObjectiveProtest(TypedDict):
    id: str
    objective_id: str
    round_index: int
    status: str
    claimed_basis_units: int
    reason: str
    resolved_units: Optional[int]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailDelivery(TypedDict):
    id: str
    dealer_id: str
    vin: str
    model_code: str
    trim_code: Optional[str]
    build_date: str
    msrp_cents: int
    sale_date: str
    customer_region_code: str
    deal_type: str
    term_months: int
    contract_apr_bps: int
    base_residual_bps: int
    status: str
    reported_at: str
    reporting_lag_days: int
    back_dated_flag: bool
    validated_by_user_id: Optional[str]
    unwound_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    delivery_id: Optional[str]
    program_id: str
    dealer_id: str
    claim_type: str
    claimed_amount_cents: int
    snapshot_per_unit_cents: int
    approved_amount_cents: Optional[int]
    rate_basis: Optional[str]
    validation_status: str
    payment_status: str
    payment_batch_id: Optional[str]
    rejection_error_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentBatch(TypedDict):
    id: str
    batch_code: str
    region_code: str
    period_start: str
    period_end: str
    scheduled_pay_date: str
    status: str
    claim_count: int
    total_cents: int
    held_claim_count: int
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict):
    id: str
    claim_id: str
    reason: str
    amount_cents: int
    status: str
    created_by_user_id: Optional[str]
    recovered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetAccrual(TypedDict):
    id: str
    program_id: str
    period_month: str
    entry_type: str
    accrual_method: str
    accrued_cents: int
    reversal_cents: int
    unit_basis: int
    source_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepricingEvent(TypedDict):
    id: str
    program_id: str
    mode: str
    previous_per_unit_amount_cents: int
    new_per_unit_amount_cents: int
    effective_at: str
    month_start: str
    affected_claim_count: int
    net_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


# The two append-only configuration resources of PRD §2.4 carry ONLY
# id and created_at — no updated_at and no version field at all.


class EligibilityRule(TypedDict):
    id: str
    program_id: str
    model_code: str
    trim_code: Optional[str]
    region_code: str
    build_date_from: str
    build_date_to: str
    min_msrp_cents: int
    max_msrp_cents: Optional[int]
    allowed_deal_types: List[str]
    created_at: str


class StackabilityConstraint(TypedDict):
    id: str
    program_a_id: str
    program_b_id: str
    mode: str
    cap_amount_cents: Optional[int]
    created_at: str
