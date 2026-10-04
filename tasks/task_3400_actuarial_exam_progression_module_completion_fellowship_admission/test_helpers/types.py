"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity narratives (§2.5, §2.9, §3.1-§3.9). Every resource
in this API carries id, created_at, updated_at and version without exception
(PRD §2.5: "No resource type in this system omits updated_at or version").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CANDIDATE = "Candidate"
    REGISTRAR = "Registrar"
    EXAM_COMMITTEE = "ExamCommittee"
    ACADEMIC_REVIEWER = "AcademicReviewer"
    GRADER = "Grader"
    DISCIPLINE_BOARD = "DisciplineBoard"


# ---------------------------------------------------------------------------
# Status / enum types
# ---------------------------------------------------------------------------
class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPELLED = "EXPELLED"


class MembershipTier(str, Enum):
    CANDIDATE = "CANDIDATE"
    ASSOCIATE = "ASSOCIATE"
    FELLOW = "FELLOW"


class SyllabusStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ExamStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    TESTING = "TESTING"
    SCORING = "SCORING"
    RESULTS_PUBLISHED = "RESULTS_PUBLISHED"
    CANCELLED = "CANCELLED"


class LogisticsStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    SAT = "SAT"
    CANCELLED = "CANCELLED"


class GradingStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CancelReason(str, Enum):
    CANDIDATE = "CANDIDATE"
    DISCIPLINE_SUSPENSION = "DISCIPLINE_SUSPENSION"
    DISCIPLINE_EXPULSION = "DISCIPLINE_EXPULSION"
    SYLLABUS_RETIREMENT = "SYLLABUS_RETIREMENT"


class PassMarkStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class VeeTopic(str, Enum):
    ECONOMICS = "ECONOMICS"
    CORPORATE_FINANCE = "CORPORATE_FINANCE"
    APPLIED_STATISTICS = "APPLIED_STATISTICS"


class VeeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VeeDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class TrackCode(str, Enum):
    QFI = "QFI"
    ILA = "ILA"
    CFE = "CFE"
    RET = "RET"
    GH = "GH"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    CAPSTONE_ELIGIBLE = "CAPSTONE_ELIGIBLE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ProjectStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    SPLIT = "SPLIT"
    DECIDED = "DECIDED"


class ProjectResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class AttendanceStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class AttendanceOutcome(str, Enum):
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class SourceBody(str, Enum):
    IFOA = "IFOA"
    CIA = "CIA"
    IAA = "IAA"
    CAS = "CAS"
    OTHER = "OTHER"


class AgreementClass(str, Enum):
    BILATERAL = "BILATERAL"
    NON_BILATERAL = "NON_BILATERAL"
    UNRECOGNIZED = "UNRECOGNIZED"


class TransferStatus(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class CpdStatus(str, Enum):
    ATTESTED = "ATTESTED"
    VERIFIED = "VERIFIED"
    SHORTFALL = "SHORTFALL"


class CaseStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"


class Resolution(str, Enum):
    DISMISSED = "DISMISSED"
    REPRIMAND = "REPRIMAND"
    SUSPENSION = "SUSPENSION"
    EXPULSION = "EXPULSION"


class Credential(str, Enum):
    ASA = "ASA"
    FSA = "FSA"


class ApplicationStatus(str, Enum):
    APPROVED = "APPROVED"
    DENIED_DEFICIENCY = "DENIED_DEFICIENCY"


class DeficiencyCode(str, Enum):
    MISSING_PRELIM_CREDIT = "MISSING_PRELIM_CREDIT"
    MISSING_VEE_TOPIC = "MISSING_VEE_TOPIC"
    INSUFFICIENT_TOTAL_CREDITS = "INSUFFICIENT_TOTAL_CREDITS"
    MISSING_ASA = "MISSING_ASA"
    TRACK_INCOMPLETE = "TRACK_INCOMPLETE"
    MISSING_PROJECT_PASS = "MISSING_PROJECT_PASS"
    MISSING_PROFESSIONALISM = "MISSING_PROFESSIONALISM"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5: all resources carry id/created_at/updated_at/
# version; system fields begin null unless a workflow defines a creation value)
# ---------------------------------------------------------------------------
class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    membership_tier: str
    status: str
    suspended_until: Optional[str]
    associate_admitted_at: Optional[str]
    fellow_admitted_at: Optional[str]
    earned_exam_credit_hours: int
    transfer_credit_hours: int
    total_credit_hours: int
    last_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SyllabusVersion(TypedDict, total=False):
    id: str
    version_code: str
    status: str
    credit_map: dict
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exam(TypedDict, total=False):
    id: str
    exam_code: str
    title: str
    credit_hours: int
    is_prelim: bool
    prerequisite_exam_id: Optional[str]
    syllabus_version_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamWindow(TypedDict, total=False):
    id: str
    exam_id: str
    window_code: str
    registration_opens_at: str
    registration_deadline: str
    testing_starts_at: str
    testing_ends_at: str
    capacity: int
    base_fee_cents: int
    late_surcharge_cents: int
    status: str
    seats_held: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class ExamRegistration(TypedDict, total=False):
    id: str
    candidate_id: str
    exam_window_id: str
    logistics_status: str
    grading_status: str
    raw_score: Optional[int]
    scaled_score: Optional[float]
    result: Optional[str]
    projected_result: Optional[str]
    fee_charged_cents: Optional[int]
    refund_cents: Optional[int]
    cancel_reason: Optional[str]
    sat_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PassMarkSetting(TypedDict, total=False):
    id: str
    exam_window_id: str
    proposed_mark: float
    ratified_mark: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class VEECourseSubmission(TypedDict, total=False):
    id: str
    candidate_id: str
    topic: str
    university: str
    course_title: str
    grade_points: float
    status: str
    reviewer_note: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrackEnrollment(TypedDict, total=False):
    id: str
    candidate_id: str
    track_code: str
    status: str
    modules_passed_count: int
    completion_pct: float
    created_at: str
    updated_at: str
    version: int


class Module(TypedDict, total=False):
    id: str
    module_code: str
    track_code: str
    sequence_index: int
    title: str
    is_capstone: bool
    passing_score: int
    cooldown_days: int
    created_at: str
    updated_at: str
    version: int


class ModuleAttempt(TypedDict, total=False):
    id: str
    track_enrollment_id: str
    module_id: str
    attempt_number: int
    status: str
    score: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectAssessment(TypedDict, total=False):
    id: str
    candidate_id: str
    track_enrollment_id: str
    title: str
    status: str
    grader_ids: List[str]
    scores: List[int]
    final_score: Optional[int]
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProfessionalismCourseSession(TypedDict, total=False):
    id: str
    session_code: str
    starts_at: str
    ends_at: str
    capacity: int
    status: str
    attendance_booked: int
    created_at: str
    updated_at: str
    version: int


class CourseAttendance(TypedDict, total=False):
    id: str
    course_session_id: str
    candidate_id: str
    status: str
    verified_at: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferCreditRequest(TypedDict, total=False):
    id: str
    candidate_id: str
    source_body: str
    claimed_hours: int
    agreement_class: str
    granted_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CPDAttestation(TypedDict, total=False):
    id: str
    candidate_id: str
    cycle_year: int
    attested_hours: float
    carryover_hours: int
    required_hours: int
    verified_hours: Optional[float]
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplineCase(TypedDict, total=False):
    id: str
    candidate_id: str
    charge: str
    severity: int
    status: str
    resolution: Optional[str]
    suspension_days: Optional[int]
    suspended_until: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialApplication(TypedDict, total=False):
    id: str
    candidate_id: str
    credential: str
    status: str
    deficiency_codes: List[str]
    evaluated_at: str
    created_at: str
    updated_at: str
    version: int
