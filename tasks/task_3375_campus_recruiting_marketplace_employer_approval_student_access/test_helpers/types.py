"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UniversityStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ALUMNUS = "ALUMNUS"
    WITHDRAWN = "WITHDRAWN"


class WorkAuthorization(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    PERMANENT_RESIDENT = "PERMANENT_RESIDENT"
    VISA_OPT_CPT = "VISA_OPT_CPT"
    SPONSORSHIP_REQUIRED = "SPONSORSHIP_REQUIRED"


class ProfileVisibility(str, Enum):
    PUBLIC_TO_APPROVED_EMPLOYERS = "PUBLIC_TO_APPROVED_EMPLOYERS"
    UNIVERSITY_ONLY = "UNIVERSITY_ONLY"
    HIDDEN = "HIDDEN"


class OutcomeStatus(str, Enum):
    UNREPORTED = "UNREPORTED"
    EMPLOYED = "EMPLOYED"
    GRAD_SCHOOL = "GRAD_SCHOOL"
    SEEKING = "SEEKING"
    OTHER = "OTHER"


class EmployerStatus(str, Enum):
    PENDING = "PENDING"
    DOMAIN_VERIFIED = "DOMAIN_VERIFIED"
    APPROVED = "APPROVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"


class TrustTier(str, Enum):
    LOW_RISK = "LOW_RISK"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH_RISK = "HIGH_RISK"


class EmployerApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class JobPostingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    # Read-time projection only (PRD §2.10); never a stored status.
    EXPIRED = "EXPIRED"


class PositionType(str, Enum):
    FULL_TIME = "FULL_TIME"
    INTERNSHIP = "INTERNSHIP"
    COOP = "COOP"


class DocumentType(str, Enum):
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    TRANSCRIPT = "TRANSCRIPT"
    PORTFOLIO = "PORTFOLIO"


class CareerEventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionMode(str, Enum):
    VIRTUAL = "VIRTUAL"
    IN_PERSON = "IN_PERSON"


class EventSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class EventSignupStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    AUTO_WITHDRAWN = "AUTO_WITHDRAWN"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    CAREER_CENTER_ADMIN = "CareerCenterAdmin"
    EMPLOYER_RECRUITER = "EmployerRecruiter"
    STUDENT = "Student"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries id, created_at, updated_at and
# version (PRD §2.4).
# ---------------------------------------------------------------------------


class University(TypedDict):
    id: str
    name: str
    primary_domain: str
    status: str
    employer_daily_message_cap: int
    enrolled_student_count: int
    approved_employer_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    university_id: str
    email: str
    full_name: str
    major: str
    graduation_year: int
    work_authorization: str
    profile_visibility: str
    status: str
    outcome_status: str
    outcome_employer_name: Optional[str]
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    company_name: str
    website_domain: str
    contact_email: str
    status: str
    domain_verification_token: Optional[str]
    fraud_risk_score: int
    trust_tier: str
    screen_count: int
    last_trust_decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerApproval(TypedDict):
    id: str
    employer_id: str
    university_id: str
    status: str
    decision_reason: Optional[str]
    decided_at: Optional[str]
    trust_tier_at_decision: Optional[str]
    supersedes_approval_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict):
    id: str
    employer_id: str
    title: str
    position_type: str
    required_majors: List[str]
    min_graduation_year: int
    max_graduation_year: int
    accepted_work_authorizations: List[str]
    required_documents: List[str]
    application_deadline: str
    status: str
    blocked_university_ids: List[str]
    active_application_count: int
    created_at: str
    updated_at: str
    version: int


class CareerEvent(TypedDict):
    id: str
    university_id: str
    title: str
    starts_at: str
    ends_at: str
    status: str
    last_session_added_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventSession(TypedDict):
    id: str
    career_event_id: str
    title: str
    mode: str
    room_id: Optional[str]
    starts_at: str
    ends_at: str
    signup_deadline: str
    capacity: int
    occupied_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventSignup(TypedDict):
    id: str
    event_session_id: str
    student_id: str
    status: str
    registered_at: Optional[str]
    promoted_from_waitlist: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    student_id: str
    job_posting_id: str
    status: str
    submitted_documents: List[dict]
    documents_status: str
    submitted_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict):
    id: str
    application_id: str
    interviewer_email: str
    mode: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachMessage(TypedDict):
    id: str
    employer_id: str
    student_id: str
    university_id: str
    body: str
    sent_day: str
    created_at: str
    updated_at: str
    version: int
