"""Domain types for the ISO Residual Accounting API.

Entity TypedDicts, status/state enums and the role enum, all derived from the
PRD. Note that a ChargebackEvent is append-only and therefore carries only
``id`` and ``created_at`` — no ``updated_at`` and no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ISO_ADMIN = "IsoAdmin"
    RESIDUAL_ANALYST = "ResidualAnalyst"
    RESIDUAL_CONTROLLER = "ResidualController"
    AGENT = "Agent"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NormalizationMode(str, Enum):
    NET_REVENUE_SPLIT = "NET_REVENUE_SPLIT"
    GROSS_SPLIT = "GROSS_SPLIT"


class MinimumBillingMode(str, Enum):
    SHORTFALL_BILLED = "SHORTFALL_BILLED"
    NO_MINIMUM = "NO_MINIMUM"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPARTURE_NOTICE = "DEPARTURE_NOTICE"
    DEPARTED = "DEPARTED"


class MerchantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ATTRITED = "ATTRITED"


class BatchState(str, Enum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ChargebackLiability(str, Enum):
    AGENT_CHARGED = "AGENT_CHARGED"
    ISO_ABSORBED = "ISO_ABSORBED"


class AllocationType(str, Enum):
    DIRECT_SPLIT = "DIRECT_SPLIT"
    OVERRIDE = "OVERRIDE"


class StatementLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    FINALIZED = "FINALIZED"


class StatementSettlementState(str, Enum):
    UNSETTLED = "UNSETTLED"
    HELD = "HELD"
    SETTLED = "SETTLED"


class AdjustmentKind(str, Enum):
    DISPUTE_CREDIT = "DISPUTE_CREDIT"
    MANUAL_DEBIT = "MANUAL_DEBIT"
    BONUS_CLAWBACK = "BONUS_CLAWBACK"
    CLAWBACK_REVERSAL = "CLAWBACK_REVERSAL"
    VESTED_BUYOUT = "VESTED_BUYOUT"


class AdjustmentState(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class AdvanceType(str, Enum):
    CASH_ADVANCE = "CASH_ADVANCE"
    PORTFOLIO_BUYOUT = "PORTFOLIO_BUYOUT"


class RecoupmentMode(str, Enum):
    PERCENT_OF_RESIDUAL = "PERCENT_OF_RESIDUAL"
    STRAIGHT_LINE_AMORTIZATION = "STRAIGHT_LINE_AMORTIZATION"


class AdvanceState(str, Enum):
    ACTIVE = "ACTIVE"
    RECOUPED = "RECOUPED"


class ProcessorProgram(TypedDict):
    id: str
    name: str
    buy_rate_bps: int
    buy_rate_per_item_cents: int
    assessment_bps: int
    normalization_mode: str
    minimum_billing_mode: str
    status: str
    posted_batch_count: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    name: str
    parent_agent_id: Optional[str]
    split_pct: float
    override_pct: float
    vesting_start_date: str
    status: str
    departure_effective_date: Optional[str]
    hierarchy_depth: int
    vested_pct: int
    vested_pct_at_departure: Optional[int]
    residual_hold: bool
    portfolio_attrition_bps: int
    lifetime_clawback_cents: int
    trailing_residual_cents: int
    advance_outstanding_cents: int
    portfolio_merchant_count: int
    created_at: str
    updated_at: str
    version: int


class AgentPortfolioSummary(TypedDict):
    agent_id: str
    portfolio_merchant_count: int
    active_merchant_count: int
    attrited_merchant_count: int
    portfolio_attrition_bps: int
    residual_hold: bool
    vested_pct: int
    trailing_residual_cents: int
    advance_outstanding_cents: int
    lifetime_clawback_cents: int


class Merchant(TypedDict):
    id: str
    owning_agent_id: str
    processor_program_id: str
    mid: str
    monthly_minimum_cents: int
    per_transaction_fee_cents: int
    equipment_lease_monthly_cents: int
    upfront_bonus_cents: int
    boarded_on: str
    status: str
    attrition_date: Optional[str]
    reactivation_date: Optional[str]
    clawed_back_bonus_cents: int
    created_at: str
    updated_at: str
    version: int


class ResidualBatch(TypedDict):
    id: str
    processor_program_id: str
    period_month: str
    coverage_start: str
    coverage_end: str
    file_checksum: str
    state: str
    line_count: int
    gross_volume_cents: int
    total_normalized_net_revenue_cents: int
    iso_retained_cents: int
    posted_at: Optional[str]
    recall_count: int
    created_at: str
    updated_at: str
    version: int


class ResidualLine(TypedDict):
    id: str
    residual_batch_id: str
    merchant_id: str
    transaction_count: int
    sales_volume_cents: int
    interchange_cents: int
    assessments_cents: int
    gross_income_cents: int
    processor_cost_cents: int
    normalized_net_revenue_cents: int
    normalization_mode_applied: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackEvent(TypedDict):
    """Append-only accounting event: only ``id`` and ``created_at`` are carried."""

    id: str
    merchant_id: str
    amount_cents: int
    occurred_on: str
    period_month: str
    liability: str
    created_at: str


class MerchantProfitability(TypedDict):
    id: str
    merchant_id: str
    residual_batch_id: str
    period_month: str
    normalized_net_revenue_cents: int
    chargeback_cost_cents: int
    agent_chargeable_chargeback_cents: int
    equipment_cost_cents: int
    profit_cents: int
    agent_basis_cents: int
    allocated_total_cents: int
    iso_retained_cents: int
    created_at: str
    updated_at: str
    version: int


class ResidualAllocation(TypedDict):
    id: str
    agent_id: str
    merchant_id: str
    statement_id: Optional[str]
    period_month: str
    allocation_type: str
    tier_level: int
    applied_pct: float
    basis_cents: int
    gross_allocation_cents: int
    vesting_withheld_cents: int
    created_at: str
    updated_at: str
    version: int


class AgentStatement(TypedDict):
    id: str
    agent_id: str
    period_month: str
    lifecycle_state: str
    settlement_state: str
    direct_residual_cents: int
    override_residual_cents: int
    minimum_true_up_cents: int
    gross_after_trueup_cents: int
    advance_recoupment_cents: int
    adjustment_cents: int
    opening_deficit_cents: int
    net_payable_cents: int
    carry_forward_deficit_cents: int
    issued_at: Optional[str]
    paid_on: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatementAdjustment(TypedDict):
    id: str
    statement_id: str
    source_merchant_id: Optional[str]
    kind: str
    amount_cents: int
    reason: str
    state: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    info_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentAdvance(TypedDict):
    id: str
    agent_id: str
    advance_type: str
    recoupment_mode: str
    principal_cents: int
    recoupment_pct: Optional[float]
    amortization_months: Optional[int]
    first_recoupment_month: str
    last_recoupment_month: str
    funded_on: str
    outstanding_cents: int
    cumulative_recouped_cents: int
    months_recouped: int
    state: str
    created_at: str
    updated_at: str
    version: int


ALL_ROLES: List[str] = [
    UserRole.ISO_ADMIN.value,
    UserRole.RESIDUAL_ANALYST.value,
    UserRole.RESIDUAL_CONTROLLER.value,
    UserRole.AGENT.value,
]
