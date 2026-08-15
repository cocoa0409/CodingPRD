"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STUDENT = "Student"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    FACULTY_APPROVER = "FacultyApprover"
    SAFETY_OFFICER = "SafetyOfficer"
    BURSAR_OFFICE = "BursarOffice"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class PartnerAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    CLEARED = "CLEARED"
    APPROVED = "APPROVED"
    COMMITTED = "COMMITTED"
    ABROAD = "ABROAD"
    RETURNED_HOME = "RETURNED_HOME"
    CREDIT_POSTED = "CREDIT_POSTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawReason(str, Enum):
    STUDENT_INITIATED = "STUDENT_INITIATED"
    STAFF_INITIATED = "STAFF_INITIATED"
    SYSTEM_SUSPENSION = "SYSTEM_SUSPENSION"


class CoursePreApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TravelAdvisoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class AdvisoryLevel(str, Enum):
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DO_NOT_TRAVEL = "DO_NOT_TRAVEL"


class InsuranceEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class BillingStatementStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class CreditPostingStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"


class Term(str, Enum):
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    FALL = "FALL"
    ACADEMIC_YEAR = "ACADEMIC_YEAR"


class BillingModel(str, Enum):
    HOME_TUITION = "HOME_TUITION"
    PROGRAM_FEE = "PROGRAM_FEE"


class ConductStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CONDUCT_REVIEW = "CONDUCT_REVIEW"
    CONDUCT_HOLD = "CONDUCT_HOLD"


class ClearanceDecision(str, Enum):
    CLEARED = "CLEARED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"


class LifecycleAction(str, Enum):
    DEPART = "DEPART"
    RECORD_RETURN = "RECORD_RETURN"


# ---------------------------------------------------------------------------
# Entity TypedDicts. All entities carry common fields (PRD §2.4):
# id, created_at, updated_at, version.
# ---------------------------------------------------------------------------

class PartnerAgreement(TypedDict, total=False):
    id: str
    host_institution: str
    country_code: str
    effective_from: str
    effective_to: str
    credit_conversion_factor: float
    insurance_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    partner_agreement_id: str
    name: str
    country_code: str
    host_institution: str
    term: str
    start_date: str
    end_date: str
    application_deadline: str
    capacity: int
    billing_model: str
    program_fee_cents: int
    min_gpa: float
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    gpa: float
    conduct_standing: str
    aid_award_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    student_id: str
    program_id: str
    aid_award_cents_snapshot: int
    status: str
    clearance_recorded_by: Optional[str]
    approved_by: Optional[str]
    withdraw_reason: Optional[str]
    transfer_credits_posted: float
    created_at: str
    updated_at: str
    version: int


class CoursePreApproval(TypedDict, total=False):
    id: str
    application_id: str
    course_code: str
    course_title: str
    host_credits: float
    home_credits_est: float
    status: str
    reviewed_by: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TravelAdvisory(TypedDict, total=False):
    id: str
    country_code: str
    level: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceEnrollment(TypedDict, total=False):
    id: str
    application_id: str
    provider: str
    coverage_start_date: str
    coverage_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict, total=False):
    id: str
    application_id: str
    billing_model_snapshot: str
    base_cents: int
    insurance_premium_cents: int
    application_fee_cents: int
    aid_portable_cents: int
    charge_cents: int
    amount_paid_cents: int
    credit_memo_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    application_id: str
    severity: str
    description: str
    reported_by: str
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditPostingLine(TypedDict, total=False):
    course_preapproval_id: str
    grade_points: float


class CreditPosting(TypedDict, total=False):
    id: str
    application_id: str
    lines: List[CreditPostingLine]
    provisional_credits: float
    final_credits: float
    posted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
