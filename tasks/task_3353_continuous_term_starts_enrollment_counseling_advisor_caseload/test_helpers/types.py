"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class TermStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    IN_SESSION = "IN_SESSION"
    CLOSED = "CLOSED"


class AuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"
    PENDING = "PENDING"


class StaffType(str, Enum):
    COUNSELOR = "COUNSELOR"
    ADVISOR = "ADVISOR"


class CompensationPlan(str, Enum):
    NON_INCENTIVE = "NON_INCENTIVE"
    INCENTIVE = "INCENTIVE"


class ApplicantStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPLIED = "APPLIED"
    ADMITTED = "ADMITTED"
    ENROLLED = "ENROLLED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    CONVERTED = "CONVERTED"


class TceStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    VOID = "VOID"


class EnrollmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    DEFERRED = "DEFERRED"


class EnrollmentIntensity(str, Enum):
    FULL_TIME = "FULL_TIME"
    HALF_TIME = "HALF_TIME"
    LESS_THAN_HALF_TIME = "LESS_THAN_HALF_TIME"


class SectionStatus(str, Enum):
    PLANNED = "PLANNED"
    STAFFING = "STAFFING"
    STAFFED = "STAFFED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class PackageStatus(str, Enum):
    PACKAGED = "PACKAGED"
    CERTIFIED = "CERTIFIED"
    DISBURSING = "DISBURSING"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"


class ScheduleEntryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class AlertTriggerType(str, Enum):
    GRADE_THRESHOLD = "GRADE_THRESHOLD"
    LATE_SUBMISSION = "LATE_SUBMISSION"


class AlertSeverity(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INTERVENTION = "INTERVENTION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class OutreachStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    REENROLLED = "REENROLLED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REGISTRAR_ADMIN = "RegistrarAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    COUNSELOR = "Counselor"
    ADVISOR = "Advisor"
    APPLICANT = "Applicant"


class Term(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    add_drop_end_date: str
    census_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    code: str
    title: str
    total_credits_required: int
    licensure_flag: bool
    created_at: str
    updated_at: str
    version: int


class StateAuthorization(TypedDict, total=False):
    # Append-only row: carries only id + created_at (PRD §2.5).
    id: str
    program_id: str
    state_code: str
    authorization_status: str
    effective_from: str
    effective_to: Optional[str]
    disclosure_text: Optional[str]
    created_at: str


class Staff(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    staff_type: str
    compensation_plan: str
    caseload_cap: int
    active_caseload_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    status: str
    assigned_counselor_id: Optional[str]
    contact_log: List[Any]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    term_id: str
    program_id: str
    disclosure_acknowledged: bool
    licensure_disclosure_acknowledged: bool
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferCreditEvaluation(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    accepted_credits: int
    in_progress_credits: int
    capped_credits: int
    remaining_credits: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    application_id: str
    term_id: str
    advisor_id: str
    enrollment_intensity: str
    tuition_cents: int
    status: str
    financial_hold: bool
    withdrawal_date: Optional[str]
    institutional_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class CourseSection(TypedDict, total=False):
    id: str
    term_id: str
    course_code: str
    capacity: int
    forecast_enrollment: int
    adjuncts_required: int
    adjunct_hires: int
    enrolled_count: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialAidPackage(TypedDict, total=False):
    id: str
    enrollment_id: str
    efc_cents: int
    status: str
    estimated_award_cents: int
    certified_award_cents: int
    disbursement_schedule: List[Any]
    disbursed_cents: int
    returned_cents: int
    retained_cents: int
    cancelled_cents: int
    created_by_officer_id: str
    created_at: str
    updated_at: str
    version: int


class EarlyAlert(TypedDict, total=False):
    id: str
    enrollment_id: str
    trigger_type: str
    observed_grade_percent: Optional[float]
    days_late: Optional[int]
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionOutreach(TypedDict, total=False):
    id: str
    enrollment_id: str
    applicant_id: str
    target_term_id: str
    status: str
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
