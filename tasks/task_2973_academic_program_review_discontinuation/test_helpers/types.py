"""Domain types for the Provost Review API: status enums, role enum, entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_CHAIR = "ProgramChair"
    EXTERNAL_REVIEWER = "ExternalReviewer"
    REVIEW_COORDINATOR = "ReviewCoordinator"
    PROVOST = "Provost"
    REGISTRAR = "Registrar"
    HR_PARTNER = "HRPartner"


class DegreeLevel(str, Enum):
    UNDERGRADUATE = "UNDERGRADUATE"
    GRADUATE = "GRADUATE"
    CERTIFICATE = "CERTIFICATE"


class ProgramLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    IMPROVEMENT_MONITORED = "IMPROVEMENT_MONITORED"
    CONSOLIDATION_PENDING = "CONSOLIDATION_PENDING"
    TEACH_OUT_PENDING = "TEACH_OUT_PENDING"
    TEACH_OUT_ACTIVE = "TEACH_OUT_ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    CONSOLIDATED = "CONSOLIDATED"


class CatalogStatus(str, Enum):
    LISTED = "LISTED"
    MARKETING_SUPPRESSED = "MARKETING_SUPPRESSED"
    ADMISSIONS_CLOSED = "ADMISSIONS_CLOSED"
    CATALOG_WITHDRAWN = "CATALOG_WITHDRAWN"


class ViabilityBand(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NONVIABLE = "NONVIABLE"
    IMPROVEMENT_ELIGIBLE = "IMPROVEMENT_ELIGIBLE"
    CONTINUE_ELIGIBLE = "CONTINUE_ELIGIBLE"


class ReviewCycleState(str, Enum):
    SELF_STUDY_OPEN = "SELF_STUDY_OPEN"
    SELF_STUDY_ACCEPTED = "SELF_STUDY_ACCEPTED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    ADDENDUM_REQUESTED = "ADDENDUM_REQUESTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    DECISION_PROPOSED = "DECISION_PROPOSED"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOTICES_PENDING = "NOTICES_PENDING"
    NOTICES_CLEARED = "NOTICES_CLEARED"


class SelfStudyState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class ResponseConcurrence(str, Enum):
    CONCUR = "CONCUR"
    PARTIAL_CONCUR = "PARTIAL_CONCUR"
    DISPUTE = "DISPUTE"


class ReviewerVisitState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REPORTED = "REPORTED"


class Recommendation(str, Enum):
    CONTINUE = "CONTINUE"
    IMPROVE = "IMPROVE"
    CONSOLIDATE = "CONSOLIDATE"
    DISCONTINUE = "DISCONTINUE"


class DecisionOutcome(str, Enum):
    CONTINUE = "CONTINUE"
    IMPROVEMENT_PLAN = "IMPROVEMENT_PLAN"
    CONSOLIDATION = "CONSOLIDATION"
    DISCONTINUATION = "DISCONTINUATION"


class DecisionState(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    EFFECTUATED = "EFFECTUATED"
    RESCINDED = "RESCINDED"
    WITHDRAWN = "WITHDRAWN"


class ImprovementState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACTIVE = "ACTIVE"
    MET = "MET"
    UNMET = "UNMET"


class AgencyType(str, Enum):
    ACCREDITOR = "ACCREDITOR"
    STATE_AGENCY = "STATE_AGENCY"
    FEDERAL = "FEDERAL"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"
    VOIDED = "VOIDED"


class NotificationOrigin(str, Enum):
    AUTO_MINTED = "AUTO_MINTED"
    MANUAL = "MANUAL"


class TeachOutPlanState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_EFFECT = "IN_EFFECT"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class GuaranteeStatus(str, Enum):
    PLANNED = "PLANNED"
    OFFERED = "OFFERED"
    SUBSTITUTED = "SUBSTITUTED"
    WAIVED = "WAIVED"


class AdvisingStatus(str, Enum):
    PENDING = "PENDING"
    ADVISED = "ADVISED"
    PLAN_SIGNED = "PLAN_SIGNED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ProjectionVariant(str, Enum):
    OPTIMISTIC_FULL_LOAD = "OPTIMISTIC_FULL_LOAD"
    CONSERVATIVE_ADVISED_LOAD = "CONSERVATIVE_ADVISED_LOAD"


class AppointmentState(str, Enum):
    ASSIGNED = "ASSIGNED"
    TEACH_OUT_RETAINED = "TEACH_OUT_RETAINED"
    REASSIGNMENT_PROPOSED = "REASSIGNMENT_PROPOSED"
    REASSIGNED = "REASSIGNED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    SEPARATED = "SEPARATED"


class TenureStatus(str, Enum):
    TENURED = "TENURED"
    TENURE_TRACK = "TENURE_TRACK"
    NON_TENURE_TRACK = "NON_TENURE_TRACK"
    ADJUNCT = "ADJUNCT"


# --- Action vocabularies (closed sets, one per action-bearing endpoint) ---

SELF_STUDY_ACTIONS = ["SUBMIT", "RETURN", "ACCEPT"]
TEACH_OUT_PLAN_ACTIONS = ["SUBMIT", "RETURN", "APPROVE", "ACTIVATE"]
DECISION_ACTIONS = ["RATIFY", "EFFECTUATE", "RESCIND", "EVALUATE_IMPROVEMENT"]
NOTIFICATION_ACTIONS = ["SEND", "ACKNOWLEDGE"]
APPOINTMENT_ACTIONS = [
    "RETAIN",
    "PROPOSE_REASSIGNMENT",
    "WITHDRAW_REASSIGNMENT",
    "CONFIRM_REASSIGNMENT",
    "ISSUE_NOTICE",
    "SEPARATE",
]
SEAT_ALLOCATION_ACTIONS = ["COMMIT", "RELEASE", "SUBSTITUTE", "WAIVE"]
STUDENT_PROGRESS_ACTIONS = ["COMPLETE", "WITHDRAW"]


# --- Entity TypedDicts -------------------------------------------------------
# Entities carrying the full audit quartet: id, created_at, updated_at, version.


class AcademicProgram(TypedDict):
    id: str
    code: str
    name: str
    degree_level: str
    department_code: str
    host_capacity_per_day: int
    lifecycle_state: str
    catalog_status: str
    catalog_status_pre_decision: Optional[str]
    consolidated_into_program_id: Optional[str]
    discontinuation_override: bool
    snapshot_count: int
    cost_per_credit_hour_rolling_cents: Optional[int]
    cost_per_credit_hour_latest_cents: Optional[int]
    composite_score: Optional[float]
    viability_band: str
    faculty_fte_baseline: float
    active_fte_total: float
    reassigned_fte_total: float
    separated_fte_total: float
    assigned_pool_fte: float
    retained_teach_out_fte: float
    reducible_fte: float
    severance_budget_cap_cents: int
    staffing_liability_cents: int
    deferred_fte: float
    created_at: str
    updated_at: str
    version: int


class ReviewCycle(TypedDict):
    id: str
    program_id: str
    cycle_year: int
    state: str
    self_study_due_at: str
    required_section_codes: List[str]
    addendum_round: int
    response_concurrence: Optional[str]
    response_text: Optional[str]
    disputed_finding_codes: List[str]
    response_submitted_at: Optional[str]
    decided_at: Optional[str]
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class SelfStudy(TypedDict):
    id: str
    cycle_id: str
    narrative: str
    section_codes: List[str]
    state: str
    revision_round: int
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    revision_notes: Optional[str]
    attestation_note: Optional[str]
    missing_section_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ExternalReviewer(TypedDict):
    id: str
    full_name: str
    institution: str
    specialty_code: str
    conflict_program_codes: List[str]
    travel_buffer_hours: int
    visit_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewerVisit(TypedDict):
    id: str
    cycle_id: str
    reviewer_id: str
    window_start_at: str
    window_end_at: str
    state: str
    span_start_date: str
    span_end_date: str
    completed_at: Optional[str]
    report_count: int
    created_at: str
    updated_at: str
    version: int


class DecisionRecord(TypedDict):
    id: str
    cycle_id: str
    outcome: str
    rationale: str
    effective_term_index: int
    receiving_program_id: Optional[str]
    improvement_target_score: Optional[float]
    improvement_review_term_index: Optional[int]
    improvement_milestones: List[str]
    state: str
    improvement_state: str
    proposed_by_user_id: str
    ratified_by_user_id: Optional[str]
    ratification_note: Optional[str]
    ratified_at: Optional[str]
    effectuated_at: Optional[str]
    rescission_reason: Optional[str]
    composite_score_at_proposal: Optional[float]
    viability_band_at_proposal: str
    notification_count: int
    unacknowledged_notification_count: int
    created_at: str
    updated_at: str
    version: int


class AgencyNotification(TypedDict):
    id: str
    decision_id: str
    agency_type: str
    agency_code: str
    status: str
    due_at: str
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    transmitted_reference: Optional[str]
    origin: str
    overdue_marked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeachOutPlan(TypedDict):
    id: str
    program_id: str
    decision_id: str
    last_admit_term_index: int
    first_teach_out_term_index: int
    final_award_term_index: int
    state: str
    plan_revision_round: int
    revision_notes: Optional[str]
    approved_at: Optional[str]
    activated_at: Optional[str]
    completed_at: Optional[str]
    guaranteed_seat_total: int
    committed_seat_total: int
    required_seat_total: int
    seat_shortfall: int
    at_risk_student_count: int
    open_student_count: int
    substituted_guarantee_count: int
    waived_guarantee_count: int
    created_at: str
    updated_at: str
    version: int


class CourseGuarantee(TypedDict):
    id: str
    teach_out_plan_id: str
    course_code: str
    term_index: int
    seats_guaranteed: int
    seats_committed: int
    seats_available: int
    status: str
    substitute_course_code: Optional[str]
    substitution_justification: Optional[str]
    waived_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisplacedStudent(TypedDict):
    id: str
    teach_out_plan_id: str
    student_number: str
    credits_remaining: int
    max_credits_per_term: int
    advised_credits_per_term: Optional[int]
    advising_status: str
    projection_variant: str
    projected_terms_remaining: int
    projected_completion_term_index: Optional[int]
    at_risk: bool
    required_seat_count: int
    committed_seat_count: int
    completion_term_index: Optional[int]
    withdrawal_reason_code: Optional[str]
    advised_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacultyAppointment(TypedDict):
    id: str
    program_id: str
    faculty_number: str
    tenure_status: str
    fte: float
    annual_salary_cents: int
    state: str
    reassigned_to_department_code: Optional[str]
    notice_days: Optional[int]
    notice_issued_at: Optional[str]
    separated_at: Optional[str]
    reassignment_withdraw_count: int
    notice_pay_cents: int
    reduction_sequence_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only records: only id and created_at. No updated_at, no version.


class ViabilityMetricSnapshot(TypedDict):
    id: str
    program_id: str
    term_code: str
    term_index: int
    enrollment_headcount: int
    credit_hours: int
    direct_cost_cents: int
    completions_count: int
    market_demand_index: int
    cost_per_credit_hour_cents: Optional[int]
    created_at: str


class ReviewerReport(TypedDict):
    id: str
    visit_id: str
    recommendation: str
    finding_codes: List[str]
    narrative: str
    sequence_number: int
    filed_at: str
    created_at: str
