"""Typed shapes and enumerations for every entity the API returns.

Each TypedDict mirrors the field list the PRD declares for that resource.
ServicePeriod, CaseNote, EligibilityAnalysis, BenefitAssessment and
TrainingRecord are append-only audit records that carry only ``id`` and
``created_at``, so their shapes deliberately omit ``updated_at`` and
``version``; every other resource carries the full common quartet.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Enums ──────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SERVICE_MEMBER = "ServiceMember"
    EMPLOYER = "Employer"
    OMBUDSMAN = "Ombudsman"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    AGENCY_REVIEWER = "AgencyReviewer"


class Branch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    COAST_GUARD = "COAST_GUARD"
    SPACE_FORCE = "SPACE_FORCE"


class Component(str, Enum):
    ARMY_RESERVE = "ARMY_RESERVE"
    NAVY_RESERVE = "NAVY_RESERVE"
    MARINE_RESERVE = "MARINE_RESERVE"
    ARMY_GUARD = "ARMY_GUARD"
    AIR_GUARD = "AIR_GUARD"


class Sector(str, Enum):
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"
    HEALTHCARE = "HEALTHCARE"
    LOGISTICS = "LOGISTICS"
    GOVERNMENT = "GOVERNMENT"
    CONSTRUCTION = "CONSTRUCTION"
    HOSPITALITY = "HOSPITALITY"
    TECHNOLOGY = "TECHNOLOGY"


class SizeTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class OrdersType(str, Enum):
    DRILL = "DRILL"
    ANNUAL_TRAINING = "ANNUAL_TRAINING"
    ACTIVE_DUTY = "ACTIVE_DUTY"
    NATIONAL_EMERGENCY = "NATIONAL_EMERGENCY"
    PRESIDENTIAL_CALLUP = "PRESIDENTIAL_CALLUP"


class IssueType(str, Enum):
    REEMPLOYMENT = "REEMPLOYMENT"
    BENEFITS = "BENEFITS"
    PENSION = "PENSION"
    DISCRIMINATION = "DISCRIMINATION"
    RETALIATION = "RETALIATION"


class ExcuseCategory(str, Enum):
    ORDERS_SHORT_FUSE = "ORDERS_SHORT_FUSE"
    OPERATIONAL_NECESSITY = "OPERATIONAL_NECESSITY"
    CLASSIFIED_MISSION = "CLASSIFIED_MISSION"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGE = "TRIAGE"
    ASSIGNED = "ASSIGNED"
    IN_MEDIATION = "IN_MEDIATION"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    ESCALATION_PENDING = "ESCALATION_PENDING"
    RESOLVED_INFORMAL = "RESOLVED_INFORMAL"
    REFERRED = "REFERRED"
    CLOSED_WITHDRAWN = "CLOSED_WITHDRAWN"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"


class OmbudsmanStatus(str, Enum):
    TRAINEE = "TRAINEE"
    CERTIFIED = "CERTIFIED"
    ON_LEAVE = "ON_LEAVE"
    EXPIRED = "EXPIRED"
    DECERTIFIED = "DECERTIFIED"


class RoundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    COUNTERED = "COUNTERED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CLOSED_MOOT = "CLOSED_MOOT"


class RoundResponse(str, Enum):
    ACCEPT = "ACCEPT"
    COUNTER = "COUNTER"
    DECLINE = "DECLINE"


class AddressedTo(str, Enum):
    EMPLOYER = "EMPLOYER"
    MEMBER = "MEMBER"


class NoteType(str, Enum):
    INTAKE = "INTAKE"
    CONTACT = "CONTACT"
    EMPLOYER_EDUCATION = "EMPLOYER_EDUCATION"
    RESOLUTION = "RESOLUTION"
    AUDIT = "AUDIT"


class AnalysisVariant(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class DurationBand(str, Enum):
    SHORT = "SHORT"
    MID = "MID"
    LONG = "LONG"


class EscalatorClass(str, Enum):
    SAME_POSITION = "SAME_POSITION"
    SENIORITY_ESCALATED = "SENIORITY_ESCALATED"
    ESCALATED_WITH_RETRAINING = "ESCALATED_WITH_RETRAINING"


class Agency(str, Enum):
    DOL_VETS = "DOL_VETS"
    DOJ_CIVIL_RIGHTS = "DOJ_CIVIL_RIGHTS"
    OPM = "OPM"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WITHDRAWN = "WITHDRAWN"


class StatementStatus(str, Enum):
    PLEDGED = "PLEDGED"
    SIGNED = "SIGNED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class AwardTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AwardStatus(str, Enum):
    NOMINATED = "NOMINATED"
    VETTED = "VETTED"
    CONFERRED = "CONFERRED"
    DECLINED = "DECLINED"


class EventTopic(str, Enum):
    RIGHTS_OVERVIEW = "RIGHTS_OVERVIEW"
    BENEFITS_BRIEFING = "BENEFITS_BRIEFING"
    EMPLOYER_RECOGNITION = "EMPLOYER_RECOGNITION"
    HIRING_FAIR = "HIRING_FAIR"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"


class ModuleCode(str, Enum):
    CORE_LAW = "CORE_LAW"
    MEDIATION_SKILLS = "MEDIATION_SKILLS"
    DOCUMENTATION = "DOCUMENTATION"
    ETHICS_NEUTRALITY = "ETHICS_NEUTRALITY"
    ELECTIVE = "ELECTIVE"


# ── Entity shapes ──────────────────────────────────────────────────────────

class ResponseMeta(TypedDict, total=False):
    """The meta block that accompanies every response."""

    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ServiceMember(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    branch: str
    component: str


class Employer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    sector: str
    size_tier: str
    resolved_case_count: int
    open_case_count: int
    recognition_tier: str


class Ombudsman(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    employer_affiliation_id: Optional[str]
    status: str
    certified_on: Optional[str]
    certification_expires_on: Optional[str]
    active_caseload: int
    total_training_hours: float


class ServicePeriod(TypedDict):
    """Append-only audit record: no updated_at, no version."""

    id: str
    created_at: str
    member_id: str
    employer_id: str
    start_date: str
    end_date: Optional[str]
    orders_type: str
    notice_given_at: Optional[str]
    duration_days: Optional[int]
    chargeable: bool


class ReemploymentCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    member_id: str
    employer_id: str
    issue_type: str
    description: str
    application_submitted_at: Optional[str]
    excuse_claimed: bool
    excuse_category: Optional[str]
    assigned_ombudsman_id: Optional[str]
    status: str
    open_round_count: int
    documentation_complete: bool
    escalated_at: Optional[str]
    closed_at: Optional[str]


class MediationRound(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    round_number: int
    proposal_text: str
    addressed_to: str
    response_deadline: str
    status: str
    response: Optional[str]
    counter_text: Optional[str]
    responded_at: Optional[str]


class CaseNote(TypedDict):
    """Append-only audit record: no updated_at, no version."""

    id: str
    created_at: str
    case_id: str
    note_type: str
    body: str
    author_role: str
    author_id: str


class EligibilityAnalysis(TypedDict):
    """Append-only audit record: no updated_at, no version."""

    id: str
    created_at: str
    case_id: str
    sequence_number: int
    variant: str
    notice_hours_advance: Optional[float]
    notice_satisfied: bool
    cumulative_chargeable_days: int
    service_limit_ok: bool
    disputed_period_duration_days: int
    duration_band: str
    application_deadline_days: int
    application_deadline_date: str
    deadline_satisfied: bool
    escalator_position_class: str
    overall_eligible: bool


class BenefitAssessment(TypedDict):
    """Append-only audit record: no updated_at, no version."""

    id: str
    created_at: str
    case_id: str
    health_continuation_months: float
    pension_credit_months_official: float
    pension_credit_months_alternate: float
    education_required: bool
    education_satisfied: bool


class Referral(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    agency: str
    summary: str
    status: str
    submitted_at: Optional[str]
    info_request_note: Optional[str]
    created_by_ombudsman_id: str


class StatementOfSupport(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employer_id: str
    signer_name: str
    signer_title: str
    term_months: int
    status: str
    signed_on: Optional[str]
    expires_on: Optional[str]


class RecognitionAward(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employer_id: str
    tier: str
    rationale: str
    nominated_by_id: str
    nominated_by_role: str
    status: str
    score_base: Optional[int]
    tier_qualified: Optional[str]
    score_bonus: Optional[int]
    score_final: Optional[int]


class OutreachEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    title: str
    venue: str
    starts_at: str
    ends_at: str
    topic: str
    status: str


class TrainingRecord(TypedDict):
    """Append-only audit record: no updated_at, no version."""

    id: str
    created_at: str
    ombudsman_id: str
    module_code: str
    hours: float
    exam_score: int
    completed_on: str
    proctor_id: str


class SectorTrendReport(TypedDict):
    sector: str
    period_start: str
    period_end: str
    total_cases: int
    repeat_employer_count: int
    resolved_count: int
    top_issue_type: Optional[str]
