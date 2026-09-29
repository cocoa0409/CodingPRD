"""Domain types for the Student Teacher Placement & Clinical Practice API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Every resource in this API carries id / created_at / updated_at /
version, so every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PLACEMENT_COORDINATOR = "PlacementCoordinator"
    CREDENTIAL_ANALYST = "CredentialAnalyst"
    SUPERVISION_LEAD = "SupervisionLead"
    ASSESSMENT_SCORER = "AssessmentScorer"
    UNIVERSITY_SUPERVISOR_USER = "UniversitySupervisorUser"
    CANDIDATE_USER = "CandidateUser"


# ─── Enumerations ─────────────────────────────────────

class ProgramTrack(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    SECONDARY = "SECONDARY"
    SPECIAL_ED = "SPECIAL_ED"


class Subject(str, Enum):
    MATH = "MATH"
    ELA = "ELA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    GENERALIST = "GENERALIST"
    SPED = "SPED"


class GradeBand(str, Enum):
    PK_3 = "PK_3"
    K_6 = "K_6"
    MG_5_9 = "MG_5_9"
    HS_9_12 = "HS_9_12"


class Term(str, Enum):
    FALL_2026 = "FALL_2026"
    SPRING_2027 = "SPRING_2027"


class EmploymentType(str, Enum):
    FULL_TIME = "FULL_TIME"
    ADJUNCT = "ADJUNCT"


class ItemType(str, Enum):
    CONTENT_EXAM = "CONTENT_EXAM"
    BACKGROUND_CLEARANCE = "BACKGROUND_CLEARANCE"
    COURSEWORK_BLOCK = "COURSEWORK_BLOCK"


class ClearanceScope(str, Enum):
    STATE_ONLY = "STATE_ONLY"
    DISTRICT_FINGERPRINT = "DISTRICT_FINGERPRINT"


class CycleType(str, Enum):
    FORMATIVE = "FORMATIVE"
    SUMMATIVE = "SUMMATIVE"


class RemovalReason(str, Enum):
    CANDIDATE_PERFORMANCE = "CANDIDATE_PERFORMANCE"
    ASSESSMENT_FAILURE = "ASSESSMENT_FAILURE"
    COOPERATING_TEACHER_MISCONDUCT = "COOPERATING_TEACHER_MISCONDUCT"
    DISTRICT_REQUEST = "DISTRICT_REQUEST"


class VoidedReason(str, Enum):
    REROUTED = "REROUTED"
    AGREEMENT_SUSPENDED = "AGREEMENT_SUSPENDED"


class ReadinessVariant(str, Enum):
    STRICT = "STRICT"
    ROLLING = "ROLLING"


class StipendVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CapacityPosture(str, Enum):
    OPEN = "OPEN"
    CAP_REACHED = "CAP_REACHED"


# ─── State enums ──────────────────────────────────────

class ReadinessStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    LAPSED = "LAPSED"


class LicensureStatus(str, Enum):
    PENDING = "PENDING"
    RECOMMENDED = "RECOMMENDED"
    DENIED = "DENIED"


class ReportStatus(str, Enum):
    UNREPORTED = "UNREPORTED"
    REPORTED_ON_TIME = "REPORTED_ON_TIME"
    REPORTED_LATE = "REPORTED_LATE"


class ReadinessItemStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class QualificationStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    QUALIFIED = "QUALIFIED"
    TRAINING_EXPIRED = "TRAINING_EXPIRED"
    DISQUALIFIED = "DISQUALIFIED"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTED = "ROUTED"
    MATCHED = "MATCHED"
    CLOSED = "CLOSED"


class PlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REMOVAL_PENDING = "REMOVAL_PENDING"
    REMOVED = "REMOVED"
    VOIDED = "VOIDED"
    COMPLETED = "COMPLETED"


class StipendStatus(str, Enum):
    NOT_ACCRUED = "NOT_ACCRUED"
    ACCRUED = "ACCRUED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    CLAWED_BACK = "CLAWED_BACK"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED_HOLD = "CANCELLED_HOLD"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    PASSED = "PASSED"
    FAILED = "FAILED"


# ─── Entity TypedDicts ────────────────────────────────

class Candidate(TypedDict):
    id: str
    candidate_code: str
    full_name: str
    program_track: str
    home_grid_x: int
    home_grid_y: int
    readiness_score: int
    readiness_status: str
    readiness_variant_used: Optional[str]
    licensure_status: str
    report_status: str
    recommended_by_user_id: Optional[str]
    recommended_at: Optional[str]
    denial_reason: Optional[str]
    reported_by_user_id: Optional[str]
    reported_at: Optional[str]
    reporting_cycle: Optional[str]
    state_report_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReadinessItem(TypedDict):
    id: str
    candidate_id: str
    item_type: str
    status: str
    exam_score: Optional[int]
    credits: Optional[float]
    clearance_scope: Optional[str]
    issued_on: str
    expires_on: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class District(TypedDict):
    id: str
    name: str
    district_code: str
    state_code: str
    requires_district_fingerprint: bool
    travel_reimbursement_enabled: bool
    created_at: str
    updated_at: str
    version: int


class PartnershipAgreement(TypedDict):
    id: str
    district_id: str
    term: str
    window_start: str
    window_end: str
    status: str
    placement_cap: int
    stipend_rate_cents_per_week: int
    allowed_subjects: List[str]
    allowed_grade_bands: List[str]
    seats_reserved: int
    seats_committed: int
    capacity_posture: str
    stipend_committed_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CooperatingTeacher(TypedDict):
    id: str
    district_id: str
    full_name: str
    site_name: str
    site_grid_x: int
    site_grid_y: int
    subject_endorsement: str
    grade_band: str
    years_experience: int
    consecutive_terms_hosted: int
    max_concurrent_candidates: int
    qualification_status: str
    training_completed_on: Optional[str]
    training_expires_on: Optional[str]
    active_placement_count: int
    disqualification_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UniversitySupervisor(TypedDict):
    id: str
    full_name: str
    employment_type: str
    primary_subject: str
    covered_grade_bands: List[str]
    home_grid_x: int
    home_grid_y: int
    max_travel_miles: int
    max_caseload_points_override: Optional[int]
    max_caseload_points: int
    caseload_points: int
    accepting_new_placements: bool
    created_at: str
    updated_at: str
    version: int


class PlacementRequest(TypedDict):
    id: str
    candidate_id: str
    preferred_district_id: Optional[str]
    term: str
    requested_subject: str
    requested_grade_band: str
    max_commute_miles: int
    term_start_date: str
    weeks_scheduled: int
    term_end_date: str
    status: str
    routing_round: int
    reroute_count: int
    excluded_cooperating_teacher_ids: List[str]
    current_placement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    request_id: str
    candidate_id: str
    cooperating_teacher_id: str
    agreement_id: str
    supervisor_id: str
    replaces_placement_id: Optional[str]
    subject: str
    grade_band: str
    start_date: str
    end_date: str
    weeks_scheduled: int
    commute_miles: int
    supervisor_points: int
    placement_status: str
    stipend_status: str
    stipend_variant: Optional[str]
    stipend_weekly_cents: int
    weeks_credited: int
    stipend_gross_cents: int
    travel_reimbursement_cents: int
    observation_compliance_ratio: float
    summative_completed_count: int
    removal_reason: Optional[str]
    removal_requested_by_role: Optional[str]
    removal_requested_by_user_id: Optional[str]
    removal_decided_by_user_id: Optional[str]
    removal_narrative: Optional[str]
    voided_reason: Optional[str]
    settlement_date: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObservationCycle(TypedDict):
    id: str
    placement_id: str
    supervisor_id: str
    sequence_no: int
    cycle_type: str
    window_start: str
    window_end: str
    status: str
    observed_at: Optional[str]
    rubric_score: Optional[float]
    reschedule_count: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceAssessment(TypedDict):
    id: str
    placement_id: str
    window_opens_at: str
    window_closes_at: str
    status: str
    attempt_no: int
    artifact_reference: Optional[str]
    submitted_at: Optional[str]
    task_planning: Optional[float]
    task_instruction: Optional[float]
    task_assessment: Optional[float]
    task_professionalism: Optional[float]
    total_score: int
    scored_by_user_id: Optional[str]
    scored_at: Optional[str]
    returned_feedback: Optional[str]
    created_at: str
    updated_at: str
    version: int
