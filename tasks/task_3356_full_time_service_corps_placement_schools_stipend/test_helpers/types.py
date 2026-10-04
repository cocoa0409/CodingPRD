"""Domain types: entity TypedDicts, status enums, role enum.

Field and state names follow the PRD's prose exactly. Every primary resource
carries ``id``, ``created_at``, ``updated_at`` and ``version``; the single
exception is the hour entry, which the PRD describes as carrying only ``id``
and ``created_at`` (no ``updated_at``, no ``version``), so its TypedDict omits
both.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SITE_DIRECTOR = "SiteDirector"
    PROGRAM_MANAGER = "ProgramManager"
    STIPEND_ADMINISTRATOR = "StipendAdministrator"
    SCHOOL_LIAISON = "SchoolLiaison"
    CORPS_MEMBER = "CorpsMember"
    APPLICANT = "Applicant"


class SiteStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class FundingPosture(str, Enum):
    FUNDED = "FUNDED"
    TIGHT = "TIGHT"
    DEFICIT = "DEFICIT"


class FundingType(str, Enum):
    DISTRICT = "DISTRICT"
    PHILANTHROPY = "PHILANTHROPY"
    FEDERAL = "FEDERAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    AMENDMENT_REVIEW = "AMENDMENT_REVIEW"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class DataSharingStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class ServiceScope(str, Enum):
    ATTENDANCE_SUPPORT = "ATTENDANCE_SUPPORT"
    LITERACY_TUTORING = "LITERACY_TUTORING"
    MATH_TUTORING = "MATH_TUTORING"
    WHOLE_SCHOOL_EVENTS = "WHOLE_SCHOOL_EVENTS"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED_ELIGIBLE = "SCREENED_ELIGIBLE"
    INTERVIEWED = "INTERVIEWED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ENROLLED = "ENROLLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"


class RejectionReason(str, Enum):
    BACKGROUND_CHECK_FAILED = "BACKGROUND_CHECK_FAILED"
    APPLICANT_WITHDREW = "APPLICANT_WITHDREW"
    OFFER_DECLINED = "OFFER_DECLINED"


class EducationLevel(str, Enum):
    LESS_THAN_HS = "LESS_THAN_HS"
    HS_DIPLOMA = "HS_DIPLOMA"
    GED = "GED"
    SOME_COLLEGE = "SOME_COLLEGE"
    ASSOCIATES = "ASSOCIATES"
    BACHELORS_PLUS = "BACHELORS_PLUS"


class CitizenshipStatus(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    US_NATIONAL = "US_NATIONAL"
    PERMANENT_RESIDENT = "PERMANENT_RESIDENT"
    OTHER = "OTHER"


class ServiceStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED_EARLY = "EXITED_EARLY"
    COMPLETED = "COMPLETED"


class StipendStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class AwardStatus(str, Enum):
    NOT_EARNED = "NOT_EARNED"
    EARNED_FULL = "EARNED_FULL"
    EARNED_PARTIAL = "EARNED_PARTIAL"
    FORFEITED = "FORFEITED"
    DISBURSED = "DISBURSED"


class ExitType(str, Enum):
    COMPLETED_TERM = "COMPLETED_TERM"
    COMPELLING_CIRCUMSTANCE = "COMPELLING_CIRCUMSTANCE"
    FOR_CAUSE = "FOR_CAUSE"
    NON_COMPELLING = "NON_COMPELLING"


class TeamStatus(str, Enum):
    FORMING = "FORMING"
    DEPLOYED = "DEPLOYED"
    UNDERSTAFFED = "UNDERSTAFFED"
    COMPLETED = "COMPLETED"
    DISSOLVED = "DISSOLVED"


class AssignmentRole(str, Enum):
    CORPS_MEMBER = "CORPS_MEMBER"
    TEAM_LEADER = "TEAM_LEADER"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class FocusListType(str, Enum):
    ATTENDANCE = "ATTENDANCE"
    LITERACY = "LITERACY"
    MATH = "MATH"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class CaseloadStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"


class HourCategory(str, Enum):
    DIRECT_SERVICE = "DIRECT_SERVICE"
    TRAINING = "TRAINING"
    FUNDRAISING = "FUNDRAISING"


class HourEntryStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"
    CLAWED_BACK = "CLAWED_BACK"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


# ── Entity bodies ─────────────────────────────────────────────────────────
# Fields marked nullable are null until the transition that stamps them.


class Site(TypedDict, total=False):
    id: str
    name: str
    city: str
    service_year_start: str
    service_year_end: str
    annual_stipend_cents: int
    district_committed_cents: int
    philanthropy_committed_cents: int
    federal_committed_cents: int
    district_received_cents: int
    philanthropy_received_cents: int
    federal_received_cents: int
    total_received_cents: int
    stipend_outlay_cents: int
    projected_obligations_cents: int
    funding_headroom_cents: int
    funding_posture: str
    cost_share_installment_1_cents: int
    cost_share_installment_2_cents: int
    cost_share_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    district_name: str
    team_size: int
    service_scope: List[str]
    annual_cost_share_cents: int
    agreement_status: str
    data_sharing_status: str
    created_at: str
    updated_at: str
    version: int


class CorpsMemberApplication(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    date_of_birth: str
    education_level: str
    citizenship_status: str
    prior_service_terms: int
    prior_full_awards_received: int
    status: str
    rejection_reason: Optional[str]
    enrolled_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorpsMember(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    service_status: str
    stipend_status: str
    award_status: str
    verified_hours_total: float
    verified_fundraising_hours: float
    projected_hours_total: float
    award_projected_cents: int
    award_amount_cents: Optional[int]
    exit_type: Optional[str]
    exit_date: Optional[str]
    net_stipend_received_cents: int
    active_assignment_count: int
    active_caseload_count: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    school_id: str
    name: str
    team_size_snapshot: int
    min_active_members: int
    backfill_limit: int
    backfill_deadline: str
    backfill_count: int
    active_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamAssignment(TypedDict, total=False):
    id: str
    team_id: str
    corps_member_id: str
    role: str
    start_date: str
    end_date: Optional[str]
    is_backfill: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    school_id: str
    external_student_ref: str
    grade_level: int
    focus_list_type: str
    baseline_attendance_pct: float
    current_attendance_pct: Optional[float]
    enrollment_status: str
    caseload_status: str
    assigned_member_id: Optional[str]
    assigned_start_date: Optional[str]
    assigned_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceHourEntry(TypedDict, total=False):
    # Append-and-review record: carries only id + created_at of the common
    # fields. No updated_at, no version.
    id: str
    corps_member_id: str
    service_date: str
    hours: float
    category: str
    description: str
    status: str
    review_reason: Optional[str]
    reviewed_by: Optional[str]
    created_at: str


class StipendPayment(TypedDict, total=False):
    id: str
    corps_member_id: str
    period_start: str
    period_end: str
    period_days: int
    base_amount_cents: int
    final_gross_cents: Optional[int]
    deduction_cents: int
    net_amount_cents: Optional[int]
    status: str
    created_by: str
    approved_by: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationReport(TypedDict, total=False):
    id: str
    school_id: str
    period_start: str
    period_end: str
    eligible_student_count: int
    improved_student_count: int
    pct_improved: float
    status: str
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
