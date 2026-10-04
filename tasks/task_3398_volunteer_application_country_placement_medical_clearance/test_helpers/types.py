"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's entity descriptions. Every persisted resource
carries id + created_at; every resource except the append-only ServiceEvent
also carries updated_at and version (PRD: "Common Resource Properties").
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    APPLICANT = "Applicant"
    PLACEMENT_OFFICER = "PlacementOfficer"
    MEDICAL_OFFICER = "MedicalOfficer"
    LEGAL_REVIEWER = "LegalReviewer"
    TRAINING_DIRECTOR = "TrainingDirector"
    COUNTRY_DIRECTOR = "CountryDirector"


class SkillCode(str, Enum):
    TEACHING_ENGLISH = "TEACHING_ENGLISH"
    MATH_SCIENCE = "MATH_SCIENCE"
    PRIMARY_HEALTH = "PRIMARY_HEALTH"
    NURSING = "NURSING"
    AGRONOMY = "AGRONOMY"
    FORESTRY = "FORESTRY"
    SMALL_BUSINESS = "SMALL_BUSINESS"
    IT = "IT"
    WATER_SANITATION = "WATER_SANITATION"
    YOUTH_DEVELOPMENT = "YOUTH_DEVELOPMENT"


class Sector(str, Enum):
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    AGRICULTURE = "AGRICULTURE"
    ENVIRONMENT = "ENVIRONMENT"
    YOUTH = "YOUTH"
    COMMUNITY_DEVELOPMENT = "COMMUNITY_DEVELOPMENT"


class CountryProgramStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AssignmentOpeningStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INTERVIEWING = "INTERVIEWING"
    EVALUATED = "EVALUATED"
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    CLEARED_TO_DEPART = "CLEARED_TO_DEPART"
    IN_TRAINING = "IN_TRAINING"
    SWORN_IN = "SWORN_IN"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"
    SEPARATED = "SEPARATED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InterviewRecommendation(str, Enum):
    STRONGLY_RECOMMEND = "STRONGLY_RECOMMEND"
    RECOMMEND = "RECOMMEND"
    NEUTRAL = "NEUTRAL"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class InvitationStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class DentalStatus(str, Enum):
    CLEAR = "CLEAR"
    NEEDS_TREATMENT = "NEEDS_TREATMENT"


class MedicalClearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DEFERRED = "DEFERRED"
    CLEARED = "CLEARED"
    CLEARED_WITH_ACCOMMODATION = "CLEARED_WITH_ACCOMMODATION"
    DENIED = "DENIED"
    VOID = "VOID"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"


class SuitabilityStatus(str, Enum):
    PENDING = "PENDING"
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class LegalOverallStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    VOID = "VOID"


class LegalLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class TrainingCohortStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    CONCLUDED = "CONCLUDED"


class TrainingEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATION = "REMEDIATION"
    SWORN_IN = "SWORN_IN"
    SEPARATED = "SEPARATED"


class VolunteerServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    EARLY_TERMINATED = "EARLY_TERMINATED"


class SitePlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    ENDED = "ENDED"


class ServiceEventType(str, Enum):
    MEDICAL_CARE = "MEDICAL_CARE"
    SAFETY_INCIDENT = "SAFETY_INCIDENT"
    SECURITY_ALERT = "SECURITY_ALERT"
    ALL_CLEAR = "ALL_CLEAR"
    COMMENDATION = "COMMENDATION"


class ServiceEventSeverity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class CompletionType(str, Enum):
    FULL = "FULL"
    EARLY = "EARLY"


class EtReason(str, Enum):
    MEDICAL = "MEDICAL"
    FAMILY = "FAMILY"
    SECURITY = "SECURITY"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class MedicalCondition(TypedDict):
    condition_code: str
    severity: int  # 1..3
    required_support_tier: int  # 1..3


# --- Entity bodies (common_fields: id, created_at, updated_at, version) ---


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    citizenship_country: str
    skills: List[str]
    languages: List[str]
    created_at: str
    updated_at: str
    version: int


class CountryProgram(TypedDict):
    id: str
    country_code: str
    name: str
    medical_support_tier: int
    required_language: str
    language_threshold_score: float
    training_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentOpening(TypedDict):
    id: str
    country_program_id: str
    sector: str
    title: str
    required_skills: List[str]
    preferred_skills: List[str]
    seats_total: int
    seats_provisional: int
    seats_committed: int
    departure_date: str
    invitation_issue_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    country_preference_ids: List[str]
    sector_preferences: List[str]
    statement: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict):
    id: str
    application_id: str
    interviewer_id: str
    scheduled_start: str
    scheduled_end: str
    motivation_score: float
    adaptability_score: float
    skill_competency_score: float
    cross_cultural_score: float
    overall_score: float
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict):
    id: str
    application_id: str
    assignment_opening_id: str
    pinned_country_program_id: str
    pinned_country_medical_tier: int
    pinned_departure_date: str
    issued_at: str
    acceptance_deadline: str
    issued_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalClearance(TypedDict):
    id: str
    application_id: str
    conditions: List[MedicalCondition]
    dental_status: str
    deferral_count: int
    max_tier_gap: int
    reviewed_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalClearance(TypedDict):
    id: str
    application_id: str
    background_check_status: str
    background_adjudicated_by: Optional[str]
    suitability_status: str
    suitability_decided_by: Optional[str]
    overall_status: str
    lifecycle: str
    created_at: str
    updated_at: str
    version: int


class TrainingCohort(TypedDict):
    id: str
    country_program_id: str
    name: str
    start_date: str
    end_date: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    application_id: str
    training_cohort_id: str
    assessment_attempts: int
    language_score: Optional[float]
    technical_score: Optional[float]
    cultural_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerService(TypedDict):
    id: str
    application_id: str
    assignment_opening_id: str
    country_program_id: str
    service_start_date: str
    expected_completion_date: str
    actual_end_date: Optional[str]
    days_served: Optional[int]
    months_served: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SitePlacement(TypedDict):
    id: str
    volunteer_service_id: str
    host_community_name: str
    counterpart_org_name: str
    counterpart_agreement_signed: bool
    has_running_water: bool
    structurally_sound: bool
    secure_locks: bool
    inspection_passed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log: carries ONLY id + created_at (no updated_at, no version).
class ServiceEvent(TypedDict):
    id: str
    volunteer_service_id: str
    event_type: str
    severity: str
    description: str
    occurred_at: str
    created_at: str


class CompletionRecord(TypedDict):
    id: str
    volunteer_service_id: str
    completion_type: str
    et_reason: Optional[str]
    months_served: int
    gross_accrued_cents: int
    allowance_paid_cents: int
    allowance_forfeited_cents: int
    nce_eligible: bool
    nce_duration_months: int
    created_at: str
    updated_at: str
    version: int
