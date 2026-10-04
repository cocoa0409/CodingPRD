"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD.md §2.5 common-fields rule: every resource carries
id + created_at + updated_at + version EXCEPT the evidence artifact record,
which is immutable and carries only id + created_at (PRD §2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CANDIDATE = "Candidate"
    ASSESSOR = "Assessor"
    SCORING_ADMINISTRATOR = "ScoringAdministrator"
    BOARD_ADMINISTRATOR = "BoardAdministrator"
    INCENTIVE_ADMINISTRATOR = "IncentiveAdministrator"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 state machines)
# ---------------------------------------------------------------------------
class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SCORING = "SCORING"
    CLOSED = "CLOSED"


class CandidateStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    ELIGIBILITY_DENIED = "ELIGIBILITY_DENIED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SubmissionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    SCORING = "SCORING"
    ADJUDICATION_REQUIRED = "ADJUDICATION_REQUIRED"
    SCORED = "SCORED"
    EXPIRED = "EXPIRED"


class ComponentKind(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    PORTFOLIO = "PORTFOLIO"


class ArtifactType(str, Enum):
    VIDEO = "VIDEO"
    STUDENT_WORK = "STUDENT_WORK"
    WRITTEN_COMMENTARY = "WRITTEN_COMMENTARY"
    RELEASE_FORM = "RELEASE_FORM"


class AssessorStatus(str, Enum):
    RECRUITED = "RECRUITED"
    IN_TRAINING = "IN_TRAINING"
    CALIBRATING = "CALIBRATING"
    CALIBRATED = "CALIBRATED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SCORE_SUBMITTED = "SCORE_SUBMITTED"
    FINALIZED = "FINALIZED"
    REASSIGNED = "REASSIGNED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"


class RenewalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"


class StipendStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVOKED = "REVOKED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class CycleComponent(TypedDict):
    code: str
    kind: str  # ASSESSMENT | PORTFOLIO
    weight: float


class CertificationCycle(TypedDict):
    id: str
    code: str
    components: List[CycleComponent]
    submission_window_open: str
    submission_window_close: str
    retake_window_close: str
    certification_threshold: float
    max_attempts_per_component: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    email: str
    license_number: str
    license_state: str
    district_code: str
    years_experience: int
    fte_fraction: float
    license_document_ref: Optional[str]
    employer_verification_ref: Optional[str]
    status: str
    eligibility_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentCenter(TypedDict):
    id: str
    name: str
    region_code: str
    slot_capacity: int
    created_at: str
    updated_at: str
    version: int


class AssessmentBooking(TypedDict):
    id: str
    candidate_id: str
    center_id: str
    cycle_id: str
    slot_start_at: str
    slot_end_at: str
    status: str
    earned_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ComponentSubmission(TypedDict):
    id: str
    candidate_id: str
    cycle_id: str
    component_code: str
    kind: str
    attempt_number: int
    prior_submission_id: Optional[str]
    status: str
    final_score: Optional[float]
    counted_score: Optional[float]
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class Artifact(TypedDict):
    """Immutable evidence record (PRD §2.5): id + created_at only.

    NO updated_at, NO version — clients must not expect them.
    """
    id: str
    submission_id: str
    artifact_type: str
    file_format: str
    file_size_mb: float
    duration_minutes: Optional[float]
    subject_student_count: Optional[int]
    created_at: str


class Assessor(TypedDict):
    id: str
    full_name: str
    email: str
    home_district_code: str
    status: str
    calibration_passes: int
    calibration_failures: int
    calibrated_at: Optional[str]
    open_assignment_count: int
    scored_read_count: int
    exact_agreement_rate: Optional[float]
    adjacent_agreement_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CalibrationBenchmark(TypedDict):
    id: str
    component_code: str
    content_domain: str
    known_score: float
    tolerance: float
    created_at: str
    updated_at: str
    version: int


class ScoringAssignment(TypedDict):
    id: str
    assessor_id: str
    submission_id: Optional[str]
    benchmark_id: Optional[str]
    read_number: int
    status: str
    score: Optional[float]
    score_submitted_at: Optional[str]
    is_within_tolerance: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    candidate_id: str
    cycle_id: str
    status: str
    weighted_total_provisional: float
    weighted_total_final: Optional[float]
    certified_at: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    evidence_type: str
    description: str
    hours: float


class RenewalApplication(TypedDict):
    id: str
    certification_id: str
    evidence_items: List[EvidenceItem]
    total_hours: float
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveProgram(TypedDict):
    id: str
    name: str
    sponsor_state: str
    sponsor_district_code: Optional[str]
    budget_total_cents: int
    budget_remaining_cents: int
    base_stipend_cents: int
    early_bird_multiplier: float
    early_bird_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StipendPayment(TypedDict):
    id: str
    program_id: str
    certification_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
