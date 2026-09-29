"""Domain types for the Equity Award Administration API.

Status enums, role enum and entity TypedDicts. Field names are exactly the ones
the PRD names. Two entities are immutable by construction and therefore carry
only ``id`` and ``created_at``: ``MobilityAssignment`` and ``TaxAllocation``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1) - matched exactly and case-sensitively
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    BOARD_MEMBER = "BoardMember"
    DELEGATED_OFFICER = "DelegatedOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARTICIPANT = "Participant"
    AUDITOR = "Auditor"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class EquityPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class ReservePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class PlanAction(str, Enum):
    FREEZE = "FREEZE"
    UNFREEZE = "UNFREEZE"
    TERMINATE = "TERMINATE"


class AuthorityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuthorityType(str, Enum):
    DELEGATED_OFFICER = "DELEGATED_OFFICER"
    COMMITTEE = "COMMITTEE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class InsiderStatus(str, Enum):
    NON_INSIDER = "NON_INSIDER"
    DESIGNATED_INSIDER = "DESIGNATED_INSIDER"
    SECTION_16_OFFICER = "SECTION_16_OFFICER"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"
    FOR_CAUSE = "FOR_CAUSE"
    RETIREMENT = "RETIREMENT"
    DEATH = "DEATH"


class AwardType(str, Enum):
    RSU = "RSU"
    PSU = "PSU"
    ISO = "ISO"
    NSO = "NSO"


FULL_VALUE_AWARD_TYPES = ["RSU", "PSU"]
OPTION_AWARD_TYPES = ["ISO", "NSO"]


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    GRANTED = "GRANTED"
    PARTIALLY_FORFEITED = "PARTIALLY_FORFEITED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class ApprovalPath(str, Enum):
    BOARD = "BOARD"
    DELEGATED = "DELEGATED"


class VestType(str, Enum):
    TIME = "TIME"
    PERFORMANCE = "PERFORMANCE"


class TrancheStatus(str, Enum):
    UNVESTED = "UNVESTED"
    VESTED = "VESTED"
    SETTLED = "SETTLED"
    FORFEITED = "FORFEITED"


class AccelerationReason(str, Enum):
    DEATH = "DEATH"
    RETIREMENT_ELIGIBILITY = "RETIREMENT_ELIGIBILITY"


class PerformanceCycleStatus(str, Enum):
    OPEN = "OPEN"
    CERTIFIED = "CERTIFIED"
    CANCELLED = "CANCELLED"


class TaxStatus(str, Enum):
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    ALLOCATED = "ALLOCATED"


class SettlementStatus(str, Enum):
    PENDING_TAX = "PENDING_TAX"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class WithholdingMethod(str, Enum):
    SHARE_WITHHOLD = "SHARE_WITHHOLD"
    SELL_TO_COVER = "SELL_TO_COVER"
    CASH_REMITTANCE = "CASH_REMITTANCE"


class TradingWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class WindowAction(str, Enum):
    OPEN = "OPEN"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    CLOSE = "CLOSE"


class PreclearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class TransactionType(str, Enum):
    SELL = "SELL"
    BUY = "BUY"
    GIFT = "GIFT"


class PreclearanceDecision(str, Enum):
    REQUEST_INFO = "REQUEST_INFO"
    APPROVE = "APPROVE"
    DENY = "DENY"


class TradingPlanStatus(str, Enum):
    PENDING_COOLING_OFF = "PENDING_COOLING_OFF"
    EFFECTIVE = "EFFECTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ReportSourceType(str, Enum):
    VESTING_SETTLEMENT = "VESTING_SETTLEMENT"
    PRECLEARANCE_EXECUTION = "PRECLEARANCE_EXECUTION"


class FormType(str, Enum):
    FORM_4 = "FORM_4"
    FORM_5 = "FORM_5"


class ReportStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    LATE_FILED = "LATE_FILED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class EquityPlan(TypedDict):
    id: str
    name: str
    status: str
    total_authorized_shares: int
    common_shares_outstanding: int
    fiscal_year_start_date: str
    current_fiscal_year_label: str
    evergreen_pct_bps: int
    evergreen_cap_shares: int
    burn_rate_limit_bps: int
    fungible_ratio_full_value_bps: int
    low_reserve_threshold_bps: int
    next_earnings_release_at: Optional[str]
    freeze_reason: Optional[str]
    shares_committed_cumulative: int
    shares_returned_cumulative: int
    fiscal_year_gross_granted_shares: int
    fiscal_year_returned_shares: int
    evergreen_topup_last_shares: int
    available_reserve_shares: int
    reserve_posture: str
    gross_burn_rate_bps: int
    net_burn_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class BurnRateSummary(TypedDict):
    plan_id: str
    gross_burn_rate_bps: int
    net_burn_rate_bps: int
    fiscal_year_gross_granted_shares: int
    fiscal_year_returned_shares: int
    burn_rate_limit_bps: int
    available_reserve_shares: int
    reserve_posture: str
    headroom_shares: int


class ApprovalAuthority(TypedDict):
    id: str
    plan_id: str
    authority_type: str
    delegate_user_id: str
    per_grant_share_cap: int
    aggregate_share_cap: int
    effective_from: str
    effective_to: str
    status: str
    consumed_shares: int
    remaining_shares: int
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    full_name: str
    employee_number: str
    home_country_code: str
    home_state_code: Optional[str]
    hire_date: str
    birth_date: str
    insider_status: str
    employment_status: str
    termination_date: Optional[str]
    termination_reason: Optional[str]
    ptep_expiry_date: Optional[str]
    age_years: int
    service_years: int
    retirement_eligible: bool
    created_at: str
    updated_at: str
    version: int


# Immutable by construction - only id and created_at, no updated_at, no version.
class MobilityAssignment(TypedDict):
    id: str
    participant_id: str
    jurisdiction_code: str
    tax_rate_bps: int
    start_date: str
    end_date: Optional[str]
    workdays: int
    created_at: str


class Grant(TypedDict):
    id: str
    plan_id: str
    participant_id: str
    award_type: str
    target_shares: int
    exercise_price_cents: int
    status: str
    changes_requested_count: int
    grant_date: Optional[str]
    approval_path: Optional[str]
    approved_under_authority_id: Optional[str]
    approved_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_at: Optional[str]
    cancel_reason: Optional[str]
    weighted_reserve_shares: int
    outstanding_shares: int
    created_at: str
    updated_at: str
    version: int


class VestingTranche(TypedDict):
    id: str
    grant_id: str
    tranche_index: int
    vest_type: str
    scheduled_vest_date: str
    target_shares: int
    shares: int
    performance_cycle_id: Optional[str]
    status: str
    acceleration_reason: Optional[str]
    vested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceCycle(TypedDict):
    id: str
    plan_id: str
    metric_code: str
    target_value: int
    certification_due_date: str
    status: str
    actual_value: Optional[int]
    payout_multiplier_bps: Optional[int]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class VestingEvent(TypedDict):
    id: str
    tranche_id: str
    vest_date: str
    sourcing_start_date: Optional[str]
    gross_shares: int
    fmv_per_share_cents: int
    taxable_income_cents: int
    withholding_method: str
    tax_status: str
    settlement_status: str
    total_workdays: int
    total_tax_cents: int
    blended_rate_bps: int
    shares_withheld: int
    shares_sold: int
    net_shares_delivered: int
    residual_cash_cents: int
    cash_due_cents: int
    vested_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable by construction - only id and created_at, no updated_at, no version.
class TaxAllocation(TypedDict):
    id: str
    vesting_event_id: str
    jurisdiction_code: str
    workdays_in_period: int
    allocation_bps: int
    tax_rate_bps: int
    tax_amount_cents: int
    created_at: str


class TradingWindow(TypedDict):
    id: str
    plan_id: str
    quarter_label: str
    open_at: str
    close_at: str
    aggregate_share_cap: Optional[int]
    status: str
    approved_shares_cumulative: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreclearanceRequest(TypedDict):
    id: str
    participant_id: str
    window_id: str
    transaction_type: str
    requested_shares: int
    intended_trade_date: str
    status: str
    revision_count: int
    valid_until: Optional[str]
    executed_shares: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    executed_at: Optional[str]
    price_per_share_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TradingPlan(TypedDict):
    id: str
    participant_id: str
    plan_document_ref: str
    first_scheduled_trade_date: str
    total_shares: int
    status: str
    adopted_at: str
    insider_status_at_adoption: str
    cooling_off_days: int
    first_trade_allowed_at: str
    modification_count: int
    termination_reason: Optional[str]
    superseded_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransactionReport(TypedDict):
    id: str
    participant_id: str
    source_type: str
    source_id: str
    form_type: str
    shares: int
    transaction_at: str
    due_at: str
    status: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
