"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_SPONSOR = "PlanSponsor"
    APPRAISER = "Appraiser"
    TRUSTEE = "Trustee"
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    PARTICIPANT = "Participant"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    OPEN = "OPEN"
    VALUATION_PENDING = "VALUATION_PENDING"
    ALLOCATION_LOCKED = "ALLOCATION_LOCKED"
    FROZEN = "FROZEN"


class RepurchasePosture(str, Enum):
    FUNDED = "FUNDED"
    UNDERFUNDED = "UNDERFUNDED"


class ForfeiturePosture(str, Enum):
    CLEAR = "CLEAR"
    SWEEP_REQUIRED = "SWEEP_REQUIRED"


class VestingSchedule(str, Enum):
    CLIFF_3YR = "CLIFF_3YR"
    GRADED_6YR = "GRADED_6YR"


class ServiceMeasurementMethod(str, Enum):
    TERMINATION_DATE_MEASURE = "TERMINATION_DATE_MEASURE"
    PLAN_YEAR_END_MEASURE = "PLAN_YEAR_END_MEASURE"


class ForfeiturePolicy(str, Enum):
    REALLOCATE_PRO_RATA = "REALLOCATE_PRO_RATA"
    REDUCE_CONTRIBUTION = "REDUCE_CONTRIBUTION"


class DistributionPolicy(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    FIVE_YEAR_INSTALLMENT = "FIVE_YEAR_INSTALLMENT"


class SweepMode(str, Enum):
    STRICT_ORDER = "STRICT_ORDER"
    BEST_FIT = "BEST_FIT"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    RETIRED = "RETIRED"
    DECEASED = "DECEASED"
    DISTRIBUTED = "DISTRIBUTED"


class TerminationReason(str, Enum):
    TERMINATION = "TERMINATION"
    RETIREMENT = "RETIREMENT"
    DEATH = "DEATH"
    DISABILITY = "DISABILITY"


class ValuationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHALLENGED = "CHALLENGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LoanStatus(str, Enum):
    AMORTIZING = "AMORTIZING"
    REPAID = "REPAID"


class ReleaseMethod(str, Enum):
    PRINCIPAL_ONLY = "PRINCIPAL_ONLY"
    PRINCIPAL_AND_INTEREST = "PRINCIPAL_AND_INTEREST"


class AllocationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class ForfeitureEventStatus(str, Enum):
    PENDING_REALLOCATION = "PENDING_REALLOCATION"
    REALLOCATED = "REALLOCATED"


class ElectionType(str, Enum):
    TERMINATION = "TERMINATION"
    RETIREMENT = "RETIREMENT"
    DEATH = "DEATH"
    DISABILITY = "DISABILITY"
    DIVERSIFICATION = "DIVERSIFICATION"


class ApprovalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PaymentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ExerciseStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    DEFERRED = "DEFERRED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PriorityClass(str, Enum):
    DEATH = "DEATH"
    RETIREMENT_DISABILITY = "RETIREMENT_DISABILITY"
    TERMINATION = "TERMINATION"
    DIVERSIFICATION = "DIVERSIFICATION"


class DeliveryStatus(str, Enum):
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"


class DeliveryChannel(str, Enum):
    EMAIL = "EMAIL"
    POSTAL = "POSTAL"
    PORTAL = "PORTAL"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
# Carries id + created_at + updated_at + version
class EsopPlan(TypedDict):
    id: str
    plan_name: str
    sponsor_name: str
    plan_year: int
    total_shares_outstanding: int
    annual_compensation_limit_cents: int
    annual_additions_limit_cents: int
    vesting_schedule: str
    service_measurement_method: str
    forfeiture_policy: str
    distribution_policy: str
    sweep_mode: str
    normal_retirement_age: int
    diversification_min_age: int
    diversification_min_years: int
    plan_status: str
    total_plan_shares: int
    suspense_shares: int
    unallocated_released_shares: int
    unallocated_forfeiture_shares: int
    reacquired_shares: int
    allocated_shares_total: int
    current_share_price_cents: int
    open_valuation_count: int
    draft_run_count: int
    repurchase_reserve_cents: int
    repurchase_reserve_floor_cents: int
    committed_repurchase_cents: int
    cumulative_repurchase_funding_cents: int
    cumulative_repurchase_settled_cents: int
    repurchase_posture: str
    forfeiture_sweep_threshold_shares: int
    forfeiture_posture: str
    frozen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    plan_id: str
    employee_number: str
    date_of_birth: str
    hire_date: str
    eligible_compensation_cents: int
    annual_hours: int
    status: str
    termination_date: Optional[str]
    termination_reason: Optional[str]
    years_of_service: int
    vested_percentage: int
    allocated_shares: int
    vested_shares: int
    distributed_shares_cumulative: int
    tendered_shares_cumulative: int
    diversified_shares_cumulative: int
    put_window_open_date: Optional[str]
    put_window_close_date: Optional[str]
    last_put_window_close_date: Optional[str]
    diversification_first_eligible_plan_year: Optional[int]
    diversification_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    plan_id: str
    plan_year: int
    appraiser_user_id: str
    enterprise_value_cents: int
    debt_outstanding_cents: int
    non_operating_assets_cents: int
    control_premium_bps: int
    marketability_discount_bps: int
    effective_from_date: str
    effective_to_date: str
    share_price_cents: int
    equity_value_cents: int
    control_premium_applied_cents: int
    ownership_bps_at_valuation: int
    status: str
    challenge_round: int
    challenge_note: Optional[str]
    supersedes_valuation_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EsopLoan(TypedDict):
    id: str
    plan_id: str
    lender_name: str
    original_principal_cents: int
    original_interest_cents: int
    shares_pledged: int
    release_method: str
    principal_balance_cents: int
    remaining_interest_cents: int
    suspense_shares: int
    released_shares_cumulative: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only servicing record: carries ONLY id + created_at
class LoanPayment(TypedDict):
    id: str
    loan_id: str
    payment_date: str
    principal_cents: int
    interest_cents: int
    suspense_shares_before: int
    released_shares: int
    suspense_shares_after: int
    release_method_applied: str
    principal_balance_after_cents: int
    remaining_interest_after_cents: int
    created_at: str


class AllocationRun(TypedDict):
    id: str
    plan_id: str
    valuation_id: str
    plan_year: int
    contributed_shares: int
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    released_shares_snapshot: int
    forfeiture_shares_snapshot: int
    pool_shares: int
    share_price_cents: int
    eligible_participant_count: int
    total_capped_compensation_cents: int
    capped_participant_count: int
    passes_executed: int
    residual_shares: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only allocation line: carries ONLY id + created_at
class ShareAllocation(TypedDict):
    id: str
    allocation_run_id: str
    participant_id: str
    capped_compensation_cents: int
    max_shares_cap: int
    gross_shares_before_cap: int
    remainder_shares_awarded: int
    excess_shares_removed: int
    allocated_shares: int
    annual_additions_cents: int
    capped: bool
    created_at: str


class ForfeitureEvent(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    plan_year: int
    forfeited_shares: int
    vested_percentage_at_forfeiture: int
    years_of_service_at_forfeiture: int
    measurement_method_applied: str
    reallocated_in_run_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionElection(TypedDict):
    id: str
    participant_id: str
    election_type: str
    requested_shares: int
    approved_shares: int
    installment_count: int
    approval_status: str
    payment_status: str
    share_price_at_election_cents: int
    commenced_at_date: Optional[str]
    diversification_year_index: Optional[int]
    diversification_cap_percent: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InstallmentPayment(TypedDict):
    id: str
    distribution_election_id: str
    sequence_number: int
    scheduled_date: str
    shares_scheduled: int
    shares_delivered: int
    paid_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PutOptionExercise(TypedDict):
    id: str
    distribution_election_id: str
    participant_id: str
    shares_tendered: int
    window_open_date: str
    window_close_date: str
    exercise_date: str
    share_price_cents: int
    exercise_amount_cents: int
    priority_class: str
    funded_cents: int
    funded_by_user_id: Optional[str]
    settled_date: Optional[str]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantStatement(TypedDict):
    id: str
    participant_id: str
    allocation_run_id: str
    plan_year: int
    opening_shares: int
    shares_allocated: int
    forfeited_shares_this_year: int
    closing_shares: int
    share_price_cents: int
    vested_percentage: int
    vested_value_cents: int
    total_value_cents: int
    diversification_eligible: bool
    delivery_status: str
    delivery_channel: Optional[str]
    created_at: str
    updated_at: str
    version: int
