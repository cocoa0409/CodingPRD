"""Domain types for the Hybrid Work Attendance Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    PEOPLE_MANAGER = "PeopleManager"
    HR_BUSINESS_PARTNER = "HRBusinessPartner"
    ACCOMMODATION_SPECIALIST = "AccommodationSpecialist"
    WORKPLACE_PROGRAM_OFFICE = "WorkplaceProgramOffice"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SYSTEM_INTEGRATION = "SystemIntegration"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class CyclePosture(str, Enum):
    OPEN = "OPEN"
    RECALIBRATING = "RECALIBRATING"
    LOCKED = "LOCKED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class EligibilityClass(str, Enum):
    FULLY_REMOTE = "FULLY_REMOTE"
    HYBRID = "HYBRID"
    ONSITE_REQUIRED = "ONSITE_REQUIRED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    BREACH = "BREACH"


class EscalationStage(str, Enum):
    NONE = "NONE"
    COACHING = "COACHING"
    WRITTEN_WARNING = "WRITTEN_WARNING"
    PERFORMANCE_PLAN = "PERFORMANCE_PLAN"
    REFERRED = "REFERRED"
    CURED = "CURED"
    CLOSED_SEPARATION = "CLOSED_SEPARATION"


class ClassificationState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_MANAGER = "PENDING_MANAGER"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class JustificationCode(str, Enum):
    ROLE_DESIGN = "ROLE_DESIGN"
    EQUIPMENT_BOUND = "EQUIPMENT_BOUND"
    CUSTOMER_ONSITE = "CUSTOMER_ONSITE"
    TALENT_RETENTION = "TALENT_RETENTION"
    ACCOMMODATION_LINKED = "ACCOMMODATION_LINKED"


class AttendanceWeekStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"
    LOCKED = "LOCKED"


class CreditVariant(str, Enum):
    SIGNAL_UNION = "SIGNAL_UNION"
    SIGNAL_CORROBORATED = "SIGNAL_CORROBORATED"


class SignalSource(str, Enum):
    BADGE = "BADGE"
    NETWORK = "NETWORK"
    MANUAL_ATTEST = "MANUAL_ATTEST"


class ExceptionCategory(str, Enum):
    MEDICAL = "MEDICAL"
    CAREGIVING = "CAREGIVING"
    DISABILITY_ACCOMMODATION = "DISABILITY_ACCOMMODATION"


class ExceptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    WITHDRAWN = "WITHDRAWN"


class RelocationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewDimensionStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class JurisdictionCode(str, Enum):
    US_CA = "US_CA"
    US_TX = "US_TX"
    US_NY = "US_NY"
    IE = "IE"
    IN = "IN"
    BR = "BR"


class DataClassificationTier(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class RelocationDecisionReason(str, Enum):
    BOTH_REVIEWS_CLEARED = "BOTH_REVIEWS_CLEARED"
    REVIEW_BLOCKED = "REVIEW_BLOCKED"
    RISK_CEILING_REACHED = "RISK_CEILING_REACHED"


class AllocationState(str, Enum):
    OPEN = "OPEN"
    TIGHT = "TIGHT"
    FROZEN = "FROZEN"


class SeatAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class DeskAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    VACATED = "VACATED"


class AssignmentMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class DemographicBand(str, Enum):
    BAND_A = "BAND_A"
    BAND_B = "BAND_B"
    BAND_C = "BAND_C"
    BAND_D = "BAND_D"


class RecalibrationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class WeekdayCode(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class PolicyCycle(TypedDict):
    id: str
    cycle_label: str
    effective_from: str
    effective_to: str
    days_in_office_floor: int
    badge_weight: float
    network_weight: float
    collaboration_target_score: float
    equity_variance_threshold_pct: float
    posture: str
    enrolled_team_count: int
    aggregate_compliance_rate: float
    formal_action_total: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    policy_cycle_id: str
    team_code: str
    expected_days_in_office_per_week: int
    core_collaboration_days: List[str]
    headcount_planned: int
    signal_corroboration_required: bool
    expected_daily_attendance: int
    base_entitlement: int
    buffer_seats_entitled: int
    entitled_seats: int
    escalated_headcount: int
    formal_action_count: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    team_id: str
    employee_number: str
    work_email: str
    home_timezone: str
    tenure_start_date: str
    demographic_band: str
    manager_user_id: str
    hr_partner_user_id: str
    disability_accommodation_on_file: bool
    status: str
    current_eligibility_class: str
    compliance_state: str
    escalation_stage: str
    cumulative_shortfall_days: int
    consecutive_breach_weeks: int
    approved_relief_days_total: int
    non_compliance_pressure: float
    created_at: str
    updated_at: str
    version: int


class EligibilityClassification(TypedDict):
    id: str
    employee_id: str
    requested_class: str
    justification_code: str
    effective_from: str
    decision_note: Optional[str]
    state: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    supersedes_classification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceWeek(TypedDict):
    id: str
    employee_id: str
    iso_week: str
    week_start_date: str
    status: str
    required_days: int
    credited_days: int
    relief_days_credited: int
    shortfall_days: int
    variant_applied: Optional[str]
    amendment_reason: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceSignal(TypedDict):
    """Immutable observation: carries only id and created_at (PRD §2.4)."""
    id: str
    attendance_week_id: str
    signal_source: str
    site_code: str
    observed_date: str
    minutes_present: int
    dedupe_key: str
    created_at: str


class ExceptionRequest(TypedDict):
    id: str
    employee_id: str
    category: str
    requested_relief_days: int
    start_date: str
    end_date: str
    rationale: str
    status: str
    granted_relief_days: int
    info_round_count: int
    info_needed: Optional[str]
    response_note: Optional[str]
    closure_reason: Optional[str]
    adjudicated_by_user_id: Optional[str]
    interactive_process_required: bool
    created_at: str
    updated_at: str
    version: int


class RemoteLocationRequest(TypedDict):
    id: str
    employee_id: str
    jurisdiction_code: str
    data_classification_tier: str
    proposed_start_date: str
    status: str
    tax_review_status: str
    security_review_status: str
    licensing_gap_count: int
    control_gap_count: int
    tax_nexus_registration_cost_cents: int
    preliminary_risk_score: int
    final_risk_score: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Neighborhood(TypedDict):
    id: str
    policy_cycle_id: str
    anchor_team_id: str
    neighborhood_code: str
    site_code: str
    seat_count: int
    buffer_seats: int
    desk_index_from: int
    desk_index_to: int
    committed_seats: int
    peak_committed_seats: int
    utilization_pct: float
    allocation_state: str
    created_at: str
    updated_at: str
    version: int


class SeatAllocation(TypedDict):
    id: str
    neighborhood_id: str
    team_id: str
    allocated_seats: int
    window_start_week: str
    window_end_week: str
    status: str
    release_reason: Optional[str]
    line_chargeback_cents: int
    weeks_in_window: int
    created_at: str
    updated_at: str
    version: int


class DeskAssignment(TypedDict):
    id: str
    seat_allocation_id: str
    employee_id: str
    desk_index: int
    start_date: str
    end_date: str
    status: str
    assignment_mode: str
    vacated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict):
    id: str
    employee_id: str
    stage: str
    opened_pressure: float
    discretionary_hold: bool
    prior_case_id: Optional[str]
    last_action_by_user_id: Optional[str]
    action_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecalibrationReview(TypedDict):
    id: str
    policy_cycle_id: str
    review_label: str
    proposed_days_in_office_delta: int
    state: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    collaboration_index: float
    equity_variance_pct: float
    total_space_chargeback_cents: int
    qualifying_band_count: int
    meets_collaboration_target: bool
    equity_flag: bool
    created_at: str
    updated_at: str
    version: int
