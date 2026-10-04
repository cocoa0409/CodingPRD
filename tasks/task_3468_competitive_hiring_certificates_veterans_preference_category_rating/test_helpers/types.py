"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the four system-managed properties of PRD §2.4
(id, created_at, updated_at, version); no append-only entities exist here.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HR_SPECIALIST = "HRSpecialist"
    HIRING_MANAGER = "HiringManager"
    SME = "SME"
    APPLICANT = "Applicant"
    SELECTING_OFFICIAL = "SelectingOfficial"
    OPM_DELEGATE = "OPMDelegate"
    SUITABILITY_REVIEWER = "SuitabilityReviewer"
    SECURITY_ADJUDICATOR = "SecurityAdjudicator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Domain enums (PRD §3)
# ---------------------------------------------------------------------------
class SensitivityLevel(str, Enum):
    NONE = "NONE"
    SECRET = "SECRET"
    TOP_SECRET = "TOP_SECRET"


class AreaOfConsideration(str, Enum):
    ALL_US_CITIZENS = "ALL_US_CITIZENS"
    STATUS_CANDIDATES = "STATUS_CANDIDATES"
    AGENCY_ONLY = "AGENCY_ONLY"


class HiringAuthority(str, Enum):
    COMPETITIVE = "COMPETITIVE"
    DIRECT_HIRE = "DIRECT_HIRE"
    VEOA = "VEOA"
    SCHEDULE_A = "SCHEDULE_A"
    NONCOMPETITIVE_SPOUSE = "NONCOMPETITIVE_SPOUSE"


class AssessmentMethod(str, Enum):
    CATEGORY_RATING = "CATEGORY_RATING"
    UNRANKED = "UNRANKED"


class VeteranPreferenceClaim(str, Enum):
    NONE = "NONE"
    FIVE_POINT = "FIVE_POINT"
    TEN_POINT_CP = "TEN_POINT_CP"
    TEN_POINT_CPS = "TEN_POINT_CPS"


class DocType(str, Enum):
    DD214 = "DD214"
    SF50 = "SF50"
    VA_LETTER = "VA_LETTER"
    SCHEDULE_A_CERT = "SCHEDULE_A_CERT"
    MILITARY_SPOUSE_ORDERS = "MILITARY_SPOUSE_ORDERS"


class QualityCategory(str, Enum):
    BEST_QUALIFIED = "BEST_QUALIFIED"
    WELL_QUALIFIED = "WELL_QUALIFIED"
    QUALIFIED = "QUALIFIED"


class PassOverReasonCode(str, Enum):
    INADEQUATE_EXPERIENCE = "INADEQUATE_EXPERIENCE"
    MISCONDUCT = "MISCONDUCT"
    OTHER = "OTHER"


class SuitabilityOutcome(str, Enum):
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class ClearanceOutcome(str, Enum):
    FAVORABLE_INTERIM = "FAVORABLE_INTERIM"
    FAVORABLE_FINAL = "FAVORABLE_FINAL"
    UNFAVORABLE = "UNFAVORABLE"


class AppealGrounds(str, Enum):
    QUALIFICATION = "QUALIFICATION"
    RATING = "RATING"
    PREFERENCE = "PREFERENCE"


class AppointmentType(str, Enum):
    COMPETITIVE = "COMPETITIVE"
    DIRECT_HIRE = "DIRECT_HIRE"
    SPECIAL_AUTHORITY = "SPECIAL_AUTHORITY"


class OfferResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class AdjudicationOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class PassOverOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Status enums (state machines)
# ---------------------------------------------------------------------------
class PositionStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"


class AnnouncementStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CERT_ISSUED = "CERT_ISSUED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUALIFIED = "QUALIFIED"
    INELIGIBLE = "INELIGIBLE"
    RATED = "RATED"
    REFERRED = "REFERRED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    HIRED = "HIRED"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CertificateEntryStatus(str, Enum):
    REFERRED = "REFERRED"
    SELECTED = "SELECTED"
    PASSED_OVER = "PASSED_OVER"
    NOT_SELECTED = "NOT_SELECTED"


class PassOverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class OfferStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    EOD_SCHEDULED = "EOD_SCHEDULED"
    ENTERED_ON_DUTY = "ENTERED_ON_DUTY"
    RESCINDED = "RESCINDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class OccupationalSeries(TypedDict, total=False):
    id: str
    series_code: str
    title: str
    min_grade: int
    max_grade: int
    quals_base_months: int
    quals_months_per_grade_step: int
    allows_education_substitution: bool
    education_substitution_cap_months: int
    positive_education_required: bool
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    series_id: str
    title: str
    org_code: str
    factor_knowledge_level: int
    factor_supervision_level: int
    factor_complexity_level: int
    factor_impact_level: int
    total_points: int
    provisional_grade: int
    official_grade: Optional[int]  # null while DRAFT
    sensitivity_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JobAnnouncement(TypedDict, total=False):
    id: str
    position_id: str
    announcement_number: str
    area_of_consideration: str
    hiring_authority: str
    assessment_method: str
    open_at: str
    close_at: str
    vacancies_count: int
    bq_cut: int
    wq_cut: int
    certificate_validity_days: int
    remaining_vacancies: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    is_us_citizen: bool
    is_current_federal_employee: bool
    agency_code: Optional[str]
    veteran_preference_claim: str
    preference_verified: bool
    preference_points: int
    created_at: str
    updated_at: str
    version: int


class EligibilityDocument(TypedDict, total=False):
    id: str
    applicant_id: str
    doc_type: str
    verified: bool
    verified_by: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    announcement_id: str
    applicant_id: str
    submitted_at: str
    claimed_experience_months: int
    claimed_education_months: int
    self_rating_knowledge: int
    self_rating_skill: int
    self_rating_ability: int
    provisional_score: int
    provisional_category: str
    required_experience_months: Optional[int]   # null until screened
    creditable_experience_months: Optional[int]  # null until screened
    technical_score: Optional[int]              # null until RATED; null forever under UNRANKED
    quality_category: Optional[str]             # null until RATED; null forever under UNRANKED
    notified_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    application_id: str
    sme_user_id: str
    rating_knowledge: int
    rating_skill: int
    rating_ability: int
    technical_score: Optional[int]   # null until first submit
    quality_category: Optional[str]  # null until first submit
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    announcement_id: str
    issued_at: str
    expires_at: str
    extension_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateEntry(TypedDict, total=False):
    id: str
    certificate_id: str
    application_id: str
    quality_category: Optional[str]  # null on UNRANKED certificates
    preference_eligible: bool
    preference_points: int
    augmented_score: Optional[int]   # null on UNRANKED certificates
    rank_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PassOverRequest(TypedDict, total=False):
    id: str
    certificate_entry_id: str
    desired_entry_id: str
    reason_code: str
    justification: str
    adjudicated_by: Optional[str]  # null until adjudicated
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    certificate_entry_id: str
    tentative_offered_at: str
    response_due_at: str
    responded_at: Optional[str]             # null while TENTATIVE
    suitability_reviewer_id: Optional[str]  # null until suitability recorded
    eod_date: Optional[str]                 # null until schedule-eod
    status: str
    created_at: str
    updated_at: str
    version: int


class SuitabilityReview(TypedDict, total=False):
    id: str
    offer_id: str
    reviewer_id: str
    outcome: str
    notes: Optional[str]
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class SecurityClearance(TypedDict, total=False):
    id: str
    offer_id: str
    adjudicator_id: str
    level_required: str
    outcome: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    application_id: str
    grounds: str
    corrected_experience_months: Optional[int]  # required iff grounds == QUALIFICATION
    filed_at: str
    deadline_at: str
    adjudication_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    offer_id: str
    appointment_type: str
    eod_date: str
    created_at: str
    updated_at: str
    version: int
