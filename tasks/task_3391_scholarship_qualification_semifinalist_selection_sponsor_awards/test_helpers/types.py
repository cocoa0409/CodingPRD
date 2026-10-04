"""Domain types: entity TypedDicts, status enums, role enum.

Entity field sets follow the PRD's per-entity field semantics. Per PRD §2.4,
most resources carry id + created_at + updated_at + version; School is the
single exception and carries only id + created_at, so its TypedDict omits
updated_at and version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SCHOOL_OFFICIAL = "SchoolOfficial"
    STUDENT = "Student"
    SPONSOR_ADMIN = "SponsorAdmin"
    COLLEGE_ADMIN = "CollegeAdmin"


class ProgramCycleStatus(str, Enum):
    SETUP = "SETUP"
    ENTRY_OPEN = "ENTRY_OPEN"
    ENTRY_CLOSED = "ENTRY_CLOSED"
    SEMIFINALISTS_SELECTED = "SEMIFINALISTS_SELECTED"
    FINALISTS_SELECTED = "FINALISTS_SELECTED"
    AWARDS_COMPLETED = "AWARDS_COMPLETED"


class StateAllocationStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CitizenshipStatus(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    US_NATIONAL = "US_NATIONAL"
    LAWFUL_PERMANENT_RESIDENT = "LAWFUL_PERMANENT_RESIDENT"
    OTHER = "OTHER"


class EnrollmentStatus(str, Enum):
    ENROLLED_FULL_TIME = "ENROLLED_FULL_TIME"
    ENROLLED_PART_TIME = "ENROLLED_PART_TIME"
    NOT_ENROLLED = "NOT_ENROLLED"


class ExamYearOfHs(str, Enum):
    SECOND_YEAR = "SECOND_YEAR"
    THIRD_YEAR = "THIRD_YEAR"


class EntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    SELECTED_SEMIFINALIST = "SELECTED_SEMIFINALIST"
    NOT_SELECTED = "NOT_SELECTED"


class CourseRigor(str, Enum):
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"
    MOST_RIGOROUS = "MOST_RIGOROUS"


class EndorsementStatus(str, Enum):
    PENDING = "PENDING"
    ENDORSED = "ENDORSED"


class ApplicationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    FINALIST_CONFIRMED = "FINALIST_CONFIRMED"
    DENIED = "DENIED"


class ReviewDecision(str, Enum):
    CONFIRM = "CONFIRM"
    RETURN = "RETURN"
    DENY = "DENY"


class SponsorAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class CollegeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class AwardCategory(str, Enum):
    NATIONAL_SINGLE = "NATIONAL_SINGLE"
    CORPORATE_SPONSORED = "CORPORATE_SPONSORED"
    COLLEGE_SPONSORED = "COLLEGE_SPONSORED"


class RecipientStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ENROLLED = "ENROLLED"
    RENEWED = "RENEWED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    LAPSED = "LAPSED"


class FundingStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COMMITTED = "COMMITTED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    FULLY_DISBURSED = "FULLY_DISBURSED"
    RELEASED_BACK = "RELEASED_BACK"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ReportedEnrollment(str, Enum):
    FULL_TIME = "FULL_TIME"
    HALF_TIME = "HALF_TIME"
    NOT_ENROLLED = "NOT_ENROLLED"


class RenewalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RenewalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class NoticeType(str, Enum):
    SEMIFINALIST_NOTICE = "SEMIFINALIST_NOTICE"
    FINALIST_NOTICE = "FINALIST_NOTICE"
    AWARD_OFFER = "AWARD_OFFER"
    PUBLIC_ANNOUNCEMENT = "PUBLIC_ANNOUNCEMENT"


class NotificationStatus(str, Enum):
    EMBARGOED = "EMBARGOED"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class ProgramCycle(TypedDict):
    id: str
    name: str
    target_graduation_year: int
    total_semifinalist_slots: int
    national_award_slots: int
    national_award_amount_cents: int
    confirming_floor: int
    application_deadline: str
    semifinalist_embargo_until: str
    finalist_embargo_until: str
    award_embargo_until: str
    public_embargo_until: str
    status: str
    matching_run: bool
    created_at: str
    updated_at: str
    version: int


class StateAllocation(TypedDict):
    id: str
    cycle_id: str
    state_code: str
    graduating_population: int
    quota_raw: Optional[float]
    slots_provisional: Optional[int]
    slots_final: Optional[int]
    threshold_selection_index: Optional[int]
    selected_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Per PRD §2.4, School carries ONLY id + created_at: no updated_at, no version.
class School(TypedDict):
    id: str
    name: str
    school_code: str
    state_code: str
    created_at: str


class Student(TypedDict):
    id: str
    full_name: str
    school_id: str
    state_code: str
    graduation_year: int
    citizenship_status: str
    enrollment_status: str
    parent_sponsor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    exam_year_of_hs: str
    reading_score: Optional[int]
    writing_score: Optional[int]
    math_score: Optional[int]
    selection_index: Optional[int]
    status: str
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinalistApplication(TypedDict):
    id: str
    entry_id: str
    student_id: str
    first_choice_college_id: Optional[str]
    gpa_scaled: float
    course_rigor: str
    confirming_selection_index: int
    endorsement_status: str
    endorsed_by_school_id: Optional[str]
    status: str
    return_reason: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorporateSponsor(TypedDict):
    id: str
    legal_name: str
    sponsor_code: str
    created_at: str
    updated_at: str
    version: int


class SponsorAgreement(TypedDict):
    id: str
    sponsor_id: str
    cycle_id: str
    supersedes_agreement_id: Optional[str]
    award_amount_cents: int
    max_awards: int
    pool_total_cents: int
    employee_children_only: bool
    min_selection_index: Optional[int]
    effective_start_date: str
    effective_end_date: str
    pool_committed_cents: int
    pool_paid_cents: int
    pool_available_reserved_cents: int
    pool_available_cash_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollegeInstitution(TypedDict):
    id: str
    legal_name: str
    college_code: str
    award_amount_cents: int
    renewable_years_total: int
    terms_per_year: int
    pool_total_cents: int
    max_awards: int
    pool_committed_cents: int
    pool_paid_cents: int
    pool_available_reserved_cents: int
    pool_available_cash_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    cycle_id: str
    application_id: str
    student_id: str
    agreement_id: Optional[str]
    college_id: Optional[str]
    category: str
    amount_cents: int
    terms_total: int
    renewable_years_total: int
    years_renewed: int
    recipient_status: str
    funding_status: str
    selection_index_snapshot: int
    offered_logical_at: str
    acceptance_deadline: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    award_id: str
    term_index: int
    academic_year_index: int
    scheduled_date: str
    amount_cents: int
    status: str
    released_logical_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalVerification(TypedDict):
    id: str
    award_id: str
    academic_year_index: int
    reported_enrollment: str
    reported_gpa: float
    status: str
    submitted_by_college_id: str
    decided_logical_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    notice_type: str
    sequence_number: int
    embargo_until: str
    status: str
    released_logical_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "ProgramCycleStatus",
    "StateAllocationStatus",
    "CitizenshipStatus",
    "EnrollmentStatus",
    "ExamYearOfHs",
    "EntryStatus",
    "CourseRigor",
    "EndorsementStatus",
    "ApplicationStatus",
    "ReviewDecision",
    "SponsorAgreementStatus",
    "CollegeStatus",
    "AwardCategory",
    "RecipientStatus",
    "FundingStatus",
    "DisbursementStatus",
    "ReportedEnrollment",
    "RenewalStatus",
    "RenewalDecision",
    "NoticeType",
    "NotificationStatus",
    "ProgramCycle",
    "StateAllocation",
    "School",
    "Student",
    "Entry",
    "FinalistApplication",
    "CorporateSponsor",
    "SponsorAgreement",
    "CollegeInstitution",
    "Award",
    "Disbursement",
    "RenewalVerification",
    "Notification",
]
