"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API is declared with common fields enabled, so every
persisted resource carries `id`, `created_at`, `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MUNICIPALITY_ADMIN = "MunicipalityAdmin"
    OPERATOR_ADMIN = "OperatorAdmin"
    EMPLOYEE = "Employee"


class Municipality(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    population_served: int
    owns_treatment_works: bool
    benchmark_index_baseline: float
    total_operator_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    municipality_id: str
    title: str
    award_date: str
    contract_start_date: str
    contract_end_date: str
    annual_fee_cents: int
    operator_penalty_share_pct: float
    staffing_floor_fte: float
    status: str
    baseline_frozen: bool
    baseline_asset_count: int
    renewal_round: int
    total_operator_penalty_cents: int
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class PerformanceStandard(TypedDict, total=False):
    id: str
    contract_id: str
    code: str
    title: str
    metric_type: str
    criticality_weight: float
    threshold_value: float
    threshold_direction: str
    breach_penalty_cents: int
    status: str
    breach_reason_code: str
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class PerformanceMeasurement(TypedDict, total=False):
    id: str
    performance_standard_id: str
    period_start: str
    period_end: str
    measured_value: float
    in_breach: bool
    weighted_breach_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffingCommitment(TypedDict, total=False):
    id: str
    contract_id: str
    role_code: str
    committed_fte: float
    filled_fte: float
    vacancy_fte: float
    status: str
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    contract_id: str
    role_code: str
    full_name: str
    municipal_hire_date: str
    municipal_years_of_service: float
    transfer_offer_fte: float
    benefit_tier: str
    pension_offset_cents: int
    status: str
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    contract_id: str
    asset_tag: str
    asset_class: str
    install_year: int
    useful_life_years: int
    criticality_rank: int
    condition_score: float
    condition_band: str
    status: str
    replacement_flagged_at: str
    created_at: str
    updated_at: str
    version: int


class AssetConditionAssessment(TypedDict, total=False):
    id: str
    asset_id: str
    assessed_at: str
    assessed_score: float
    is_baseline: bool
    assessor_party: str
    status: str
    baseline_binding: bool
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    contract_id: str
    permit_number: str
    permit_type: str
    regulator: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAllocation(TypedDict, total=False):
    id: str
    permit_id: str
    contract_id: str
    violation_code: str
    total_penalty_cents: int
    operator_share_cents: int
    municipality_share_cents: int
    state_baseline_share_cents: int
    status: str
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    asset_id: str
    contract_id: str
    work_type: str
    expense_class: str
    estimated_cost_cents: int
    actual_cost_cents: int
    cost_variance_cents: int
    documentation_complete: bool
    submitted_to_municipality_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PMSchedule(TypedDict, total=False):
    id: str
    asset_id: str
    contract_id: str
    frequency_days: int
    duration_hours: float
    next_due_at: str
    compliance_rate_pct: float
    missed_occurrence_count: int
    status: str
    status_changed_at: str
    created_at: str
    updated_at: str
    version: int


class EmergencyEvent(TypedDict, total=False):
    id: str
    contract_id: str
    asset_id: str
    event_type: str
    severity: str
    occurred_at: str
    notify_deadline_at: str
    notified_at: str
    notification_late: bool
    response_minutes: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalProposal(TypedDict, total=False):
    id: str
    contract_id: str
    round_number: int
    proposed_fee_cents: int
    proposed_term_years: int
    submitted_by: str
    benchmark_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitionObligation(TypedDict, total=False):
    id: str
    contract_id: str
    obligation_type: str
    due_at: str
    completed_at: str
    is_critical: bool
    penalty_per_day_cents: int
    outstanding_days: int
    withholding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- enum value lists (used by assertions) ----------------------------------

CONTRACT_STATUSES = [
    "AWARDED", "MOBILIZING", "OPERATING", "UNDER_REVIEW",
    "RENEWAL_PENDING", "RENEWED", "HANDING_BACK", "TRANSITIONED", "TERMINATED",
]
ASSET_STATUSES = [
    "REGISTERED", "BASELINE_ASSESSED", "BASELINE_DISPUTED", "IN_SERVICE",
    "REPLACEMENT_FLAGGED", "REPLACED", "OUT_OF_SERVICE", "RETIRED",
]
ASSET_CLASSES = [
    "MAIN", "PUMP", "VALVE", "TREATMENT_UNIT", "BLOWER", "FILTER",
    "LIFT_STATION", "RESERVOIR",
]
CONDITION_BANDS = ["EXCELLENT", "GOOD", "FAIR", "POOR", "CRITICAL"]
WORK_ORDER_STATUSES = [
    "DRAFT", "SCHEDULED", "IN_PROGRESS", "PAUSED", "AWAITING_PARTS",
    "COMPLETED", "VERIFIED", "CLOSED", "RETURNED", "CANCELLED",
]
EXPENSE_CLASSES = [
    "OPERATING", "CAPITAL_THRESHOLD", "CAPITAL_LIFE_EVENT",
    "PENDING_CLASSIFICATION", "REJECTED_AS_CAPITAL",
]
METRIC_TYPES = [
    "TREATMENT_EFFLUENT", "COLLECTION_OVERFLOW", "RESPONSE_TIME",
    "PM_COMPLETION", "WORK_ORDER_CLOSURE", "STAFFING_LEVEL",
]
STANDARD_STATUSES = ["DRAFT", "ACTIVE", "BREACHED", "SUSPENDED", "RETIRED"]
MEASUREMENT_STATUSES = ["RECORDED", "ASSESSED", "DISPUTED", "CONFIRMED", "WAIVED"]
PERMIT_STATUSES = [
    "APPLICATION_DRAFTED", "SUBMITTED", "ISSUED", "ACTIVE",
    "NOTICE_OF_VIOLATION", "RENEWAL_FILED", "SUSPENDED", "EXPIRED",
]
ALLOCATION_STATUSES = ["ALLOCATED", "CONTESTED", "ADJUSTED", "SETTLED", "VOIDED"]
EMERGENCY_STATUSES = [
    "REPORTED", "DISPATCHED", "CONTAINED", "RESTORED", "NOTIFIED",
    "ESCALATED", "UNDER_INVESTIGATION", "CLOSED",
]
PROPOSAL_STATUSES = [
    "DRAFTED", "SUBMITTED", "UNDER_REVIEW", "COUNTERED",
    "ACCEPTED", "REJECTED", "WITHDRAWN", "LAPSED",
]
OBLIGATION_STATUSES = [
    "DRAFT", "PENDING", "IN_PROGRESS", "OVERDUE", "DISPUTED",
    "ESCALATED", "SATISFIED", "WAIVED",
]
EMPLOYEE_STATUSES = [
    "MUNICIPAL", "OFFERED", "ACCEPTED", "TRANSFERRED", "INDUCTION",
    "ACTIVE", "DECLINED", "WITHDRAWN", "SEPARATED",
]
STAFFING_STATUSES = ["DRAFT", "BINDING", "SHORTFALL", "REMEDIATING", "SATISFIED", "SUSPENDED"]
PM_STATUSES = ["DRAFT", "ACTIVE", "DUE", "OVERDUE", "SUSPENDED", "COMPLETED", "RETIRED"]
ASSESSMENT_STATUSES = ["DRAFTED", "SUBMITTED", "DISPUTED", "REVISED", "ACCEPTED"]