"""Domain types: entity TypedDicts, status enums, role enum (PRD §3-§4)."""
from enum import Enum
from typing import Optional, TypedDict


# --- Status enums ---

class TrainingCenterStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class TrainingSiteStatus(str, Enum):
    PENDING_ALIGNMENT = "PENDING_ALIGNMENT"
    ALIGNED = "ALIGNED"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class InstructorStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    MONITORED = "MONITORED"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class AlignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class GuidelinesVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CourseSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RosterEntryStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_CLEAN = "CLOSED_CLEAN"
    CLOSED_CORRECTIVE = "CLOSED_CORRECTIVE"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class VerificationResult(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Discipline(str, Enum):
    BLS = "BLS"
    ACLS = "ACLS"
    PALS = "PALS"
    HEARTSAVER = "HEARTSAVER"


class CourseType(str, Enum):
    BLS_PROVIDER = "BLS_PROVIDER"
    ACLS_PROVIDER = "ACLS_PROVIDER"
    PALS_PROVIDER = "PALS_PROVIDER"
    HEARTSAVER = "HEARTSAVER"
    BLS_INSTRUCTOR = "BLS_INSTRUCTOR"


class DeliveryFormat(str, Enum):
    CLASSROOM = "CLASSROOM"
    BLENDED_SKILLS_SESSION = "BLENDED_SKILLS_SESSION"


class CancelReason(str, Enum):
    MANUAL = "MANUAL"
    GUIDELINES_TRANSITION = "GUIDELINES_TRANSITION"
    CENTER_SUSPENDED = "CENTER_SUSPENDED"
    SITE_SUSPENDED = "SITE_SUSPENDED"
    INSTRUCTOR_SUSPENDED = "INSTRUCTOR_SUSPENDED"


class UserRole(str, Enum):
    NATIONAL_ADMIN = "NationalAdmin"
    TC_ADMIN = "TCAdmin"
    TC_COORDINATOR = "TCCoordinator"
    INSTRUCTOR = "Instructor"
    TRAINING_FACULTY = "TrainingFaculty"
    QA_AUDITOR = "QAAuditor"
    EMPLOYER = "Employer"


# --- Entity TypedDicts ---
# Common-field entities (PRD §2.7): id, created_at, updated_at, version.
# Ledger entities carry only id and created_at.

class TrainingCenter(TypedDict):
    id: str
    legal_name: str
    region: str
    contact_email: str
    status: str
    probation_started_at: Optional[str]
    last_audit_opened_at: Optional[str]
    cards_issued_count: int
    active_card_count: int
    created_at: str
    updated_at: str
    version: int


class TrainingSite(TypedDict):
    id: str
    training_center_id: str
    name: str
    street_address: str
    city: str
    state_code: str
    capacity_students: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    discipline: str
    home_training_center_id: str
    legacy_certified: bool
    status: str
    certified_since: Optional[str]
    renewal_due_at: Optional[str]
    renewal_count: int
    is_faculty: bool
    sessions_taught_count: int
    created_at: str
    updated_at: str
    version: int


class TCAlignment(TypedDict):
    id: str
    training_center_id: str
    instructor_id: str
    as_faculty: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseMonitoring(TypedDict):
    # append-only ledger: no updated_at, no version (PRD §2.7)
    id: str
    instructor_id: str
    monitoring_faculty_id: str
    monitored_at: str
    course_type_observed: str
    outcome: str
    created_at: str


class TeachingEvaluation(TypedDict):
    # append-only ledger: no updated_at, no version (PRD §2.7)
    id: str
    instructor_id: str
    evaluator_faculty_id: str
    score: int
    notes: str
    created_at: str


class GuidelinesVersion(TypedDict):
    id: str
    code: str
    title: str
    published_at: str
    transition_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseSession(TypedDict):
    id: str
    training_center_id: str
    site_id: str
    primary_instructor_id: str
    guidelines_version_id: str
    course_type: str
    delivery_format: str
    start_at: str
    end_at: str
    capacity: int
    manikin_count: int
    aed_trainer_count: int
    assisting_instructor_count: int
    status: str
    cancel_reason: Optional[str]
    seats_available: int
    curriculum_flag: str
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict):
    id: str
    course_session_id: str
    student_name: str
    student_email: str
    prior_card_id: Optional[str]
    status: str
    remediation_used: bool
    created_at: str
    updated_at: str
    version: int


class SkillsEvaluation(TypedDict):
    # append-only ledger: no updated_at, no version (PRD §2.7)
    id: str
    roster_entry_id: str
    evaluated_by_instructor_id: str
    attempt_number: int
    is_remediation_retest: bool
    items: list
    total_items: int
    passed_items: int
    score_percent: float
    outcome: str
    created_at: str


class CourseCompletionCard(TypedDict):
    id: str
    roster_entry_id: str
    training_center_id: str
    prior_card_id: Optional[str]
    is_renewal: bool
    card_code: str
    verification_token: str
    holder_email: str
    course_type: str
    guidelines_version_code: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict):
    id: str
    target_training_center_id: str
    opened_by: str
    status: str
    compliance_score: float
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    # append-only ledger: no updated_at, no version (PRD §2.7)
    id: str
    audit_id: str
    severity: str
    is_repeat_offense: bool
    description: str
    deduction_points: float
    created_at: str


class CardVerification(TypedDict):
    # append-only ledger: no updated_at, no version (PRD §2.7)
    id: str
    card_id: str
    verifier_reference: str
    verified_at: str
    result: str
    card_expires_at: str
    created_at: str
