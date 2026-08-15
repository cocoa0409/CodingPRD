"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    HR_REVIEWER = "HRReviewer"
    DEPARTMENT_CHAIR = "DepartmentChair"
    DEAN = "Dean"
    PAYROLL_OFFICER = "PayrollOfficer"


class EducationTier(str, Enum):
    BACHELORS = "BACHELORS"
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"


class RateBasis(str, Enum):
    PER_CONTACT_HOUR = "PER_CONTACT_HOUR"
    PER_COURSE = "PER_COURSE"


class RolloverStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    ROLLED_OVER = "ROLLED_OVER"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CredentialKind(str, Enum):
    TRANSCRIPT = "TRANSCRIPT"
    DEGREE = "DEGREE"
    LICENSE = "LICENSE"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    TRAINING = "TRAINING"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ComplianceStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    COMPLIANT = "COMPLIANT"
    LAPSED = "LAPSED"


class RetentionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RETENTION_LISTED = "RETENTION_LISTED"
    NON_REAPPOINTED = "NON_REAPPOINTED"


class SectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ContractStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    CANCELLED_PRE_CENSUS = "CANCELLED_PRE_CENSUS"
    CANCELLED_LATE = "CANCELLED_LATE"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class CancellationReason(str, Enum):
    LOW_ENROLLMENT = "LOW_ENROLLMENT"
    PROGRAM_CUT = "PROGRAM_CUT"
    FACULTY_INITIATED = "FACULTY_INITIATED"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class EntryKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    CANCELLATION_PAYOUT = "CANCELLATION_PAYOUT"
    CLAWBACK = "CLAWBACK"


class SplitVariant(str, Enum):
    EQUAL_SPLIT = "EQUAL_SPLIT"
    DAYS_WEIGHTED = "DAYS_WEIGHTED"


class EntryStatus(str, Enum):
    LISTED = "LISTED"
    REAPPOINTED = "REAPPOINTED"
    NON_REAPPOINTED = "NON_REAPPOINTED"


# --- Entity TypedDicts -------------------------------------------------------
# All entities except PayrollEntry and EvaluationRecord carry
# id + created_at + updated_at + version (PRD Section 2.5).


class Department(TypedDict, total=False):
    id: str
    code: str
    name: str
    contact_hour_value: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class TermConfig(TypedDict, total=False):
    id: str
    code: str
    start_date: str
    end_date: str
    early_census_date: str
    late_census_date: str
    load_cap_units: float
    rollover_status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    department_id: str
    education_tier: str
    rate_basis: str
    base_rate_cents: int
    longevity_step_cents: int
    longevity_step_cap: int
    effective_start_date: str
    effective_end_date: str
    schedule_status: str
    published_version: int
    created_at: str
    updated_at: str
    version: int


class AdjunctPoolPosting(TypedDict, total=False):
    id: str
    department_id: str
    term_code: str
    title: str
    min_education_tier: str
    open_date: str
    close_date: str
    posting_status: str
    created_at: str
    updated_at: str
    version: int


class AdjunctApplication(TypedDict, total=False):
    id: str
    posting_id: str
    applicant_name: str
    applicant_email: str
    claimed_education_tier: str
    application_status: str
    revision_count: int
    hired_faculty_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialVerification(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    evidence_ref: str
    verified_education_tier: Optional[str]
    verification_status: str
    verified_by_hr_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdjunctFaculty(TypedDict, total=False):
    id: str
    application_id: str
    department_id: str
    legal_name: str
    education_tier: str
    hire_date: str
    compliance_status: str
    retention_status: str
    completed_terms: int
    current_term_load_units: float
    benefits_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CourseSection(TypedDict, total=False):
    id: str
    department_id: str
    term_code: str
    course_code: str
    section_code: str
    weekly_contact_hours: float
    credit_hours: int
    enrollment: int
    min_enrollment: int
    section_status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    faculty_id: str
    section_id: str
    rate_schedule_id: str
    pinned_schedule_version: int
    expected_faculty_version: int
    load_units: float
    gross_pay_cents: int
    payable_cents: int
    contract_status: str
    cancelled_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollPeriod(TypedDict, total=False):
    id: str
    period_code: str
    start_date: str
    end_date: str
    period_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD Section 2.5): only id + created_at — NO updated_at/version.
class PayrollEntry(TypedDict, total=False):
    id: str
    contract_id: str
    payroll_period_id: str
    entry_kind: str
    amount_cents: int
    split_variant: str
    posted_at: str
    reversal_of_entry_id: Optional[str]
    created_at: str


# Append-only (PRD Section 2.5): only id + created_at — NO updated_at/version.
class EvaluationRecord(TypedDict, total=False):
    id: str
    faculty_id: str
    term_code: str
    teaching_score: float
    service_score: float
    compliance_score: float
    composite_score: float
    recorded_by_dean_id: str
    created_at: str


class RetentionEntry(TypedDict, total=False):
    id: str
    faculty_id: str
    department_id: str
    list_term_code: str
    rank_position: int
    entry_status: str
    created_at: str
    updated_at: str
    version: int
