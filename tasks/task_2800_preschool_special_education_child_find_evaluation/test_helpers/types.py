"""Domain types for the Preschool Child Find API: status enums, role enum, entity TypedDicts.

Every entity in this system carries ``id``, ``created_at``, ``updated_at`` and
``version`` (PRD §2.4: "there is no entity here that omits ``updated_at`` or
``version``").
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    CHILD_FIND_COORDINATOR = "ChildFindCoordinator"
    EVALUATION_CHAIR = "EvaluationChair"
    EVALUATOR = "Evaluator"
    PLACEMENT_ADMINISTRATOR = "PlacementAdministrator"
    PARENT = "Parent"
    DISTRICT_ADMIN = "DistrictAdmin"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# ------------------------------------------------------------------------- child
class ChildStatus(str, Enum):
    NO_ACTIVE_REFERRAL = "NO_ACTIVE_REFERRAL"
    REFERRED = "REFERRED"
    IN_EVALUATION = "IN_EVALUATION"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SERVED = "SERVED"
    SERVICES_DECLINED = "SERVICES_DECLINED"
    EXITED_TO_KINDERGARTEN = "EXITED_TO_KINDERGARTEN"


class Child(TypedDict):
    id: str
    first_name: str
    last_name: str
    date_of_birth: str
    guardian_full_name: str
    district_of_residence: str
    primary_language_code: str
    interpreter_required: bool
    part_c_enrolled: bool
    part_c_exit_date: Optional[str]
    third_birthday: str
    kindergarten_eligibility_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ------------------------------------------------------------- community site
class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CommunityPreschoolSite(TypedDict):
    id: str
    name: str
    region_code: str
    licensed_capacity: int
    iep_seat_capacity: int
    reserved_iep_seat_count: int
    languages_supported: List[str]
    screening_host_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------- provider
class Discipline(str, Enum):
    SCHOOL_PSYCHOLOGIST = "SCHOOL_PSYCHOLOGIST"
    SLP = "SLP"
    OT = "OT"
    PT = "PT"
    ECSE_TEACHER = "ECSE_TEACHER"
    SOCIAL_WORKER = "SOCIAL_WORKER"
    INTERPRETER = "INTERPRETER"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class ServiceCapacityPosture(str, Enum):
    OPEN = "OPEN"
    NEAR_CAPACITY = "NEAR_CAPACITY"
    AT_CAPACITY = "AT_CAPACITY"


class EvaluationIntakePosture(str, Enum):
    OPEN = "OPEN"
    AT_CAPACITY = "AT_CAPACITY"


class Provider(TypedDict):
    id: str
    full_name: str
    discipline: str
    languages: List[str]
    home_region_code: str
    status: str
    max_weekly_service_minutes: int
    direct_weekly_service_minutes: int
    travel_overhead_minutes: int
    assigned_weekly_service_minutes: int
    service_capacity_posture: str
    max_evaluation_caseload: int
    active_evaluation_count: int
    evaluation_intake_posture: str
    max_weekly_interpreter_assignments: int
    assigned_interpreter_assignment_count: int
    is_evaluation_chair_eligible: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------- screening event
class ScreeningEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScreeningEvent(TypedDict):
    id: str
    site_id: str
    event_label: str
    window_start_utc: str
    window_end_utc: str
    slot_length_minutes: int
    slot_capacity: int
    effective_slot_capacity: int
    booked_slot_count: int
    interpreter_languages: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ----------------------------------------------------------------- screening slot
class ScreeningSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScreeningResult(str, Enum):
    PASS = "PASS"
    REFER = "REFER"
    RESCREEN = "RESCREEN"


class ScreeningSlot(TypedDict):
    id: str
    screening_event_id: str
    child_id: str
    slot_start_utc: str
    slot_end_utc: str
    requested_language_code: str
    status: str
    screening_result: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------- referral
class ReferralSource(str, Enum):
    PEDIATRICIAN = "PEDIATRICIAN"
    PART_C_TRANSITION = "PART_C_TRANSITION"
    SCREENING = "SCREENING"
    PARENT = "PARENT"
    SCHOOL = "SCHOOL"


class EligibilityPathway(str, Enum):
    PART_C_TRANSITION_DEADLINE = "PART_C_TRANSITION_DEADLINE"
    STANDARD_60_DAY = "STANDARD_60_DAY"
    AGE_INELIGIBLE = "AGE_INELIGIBLE"


class ReferralIntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONSENT_PENDING = "CONSENT_PENDING"
    EVALUATION_AUTHORIZED = "EVALUATION_AUTHORIZED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ReferralConsentStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REFUSED = "REFUSED"
    REVOKED = "REVOKED"


class Referral(TypedDict):
    id: str
    child_id: str
    source: str
    referring_provider_npi: Optional[str]
    originating_screening_slot_id: Optional[str]
    received_at: str
    age_months_at_referral: int
    eligibility_pathway: str
    intake_status: str
    consent_status: str
    consent_granted_at: Optional[str]
    evaluation_due_date: Optional[str]
    superseded_by_referral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------- consent record
class ConsentKind(str, Enum):
    EVALUATION_CONSENT = "EVALUATION_CONSENT"
    SERVICE_CONSENT = "SERVICE_CONSENT"


class ConsentDecision(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REFUSED = "REFUSED"
    REVOKED = "REVOKED"


class NoticeDeliveryMethod(str, Enum):
    HAND_DELIVERY = "HAND_DELIVERY"
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    INTERPRETED_ORAL = "INTERPRETED_ORAL"


class InterpreterModality(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEPHONIC = "TELEPHONIC"
    VIDEO = "VIDEO"


class ConsentRecord(TypedDict):
    id: str
    referral_id: str
    kind: str
    requested_at: str
    decision: str
    decided_at: Optional[str]
    notice_language_code: str
    notice_delivery_method: str
    interpreter_provider_id: Optional[str]
    interpreter_modality: Optional[str]
    service_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------- evaluation case
class AssessmentProtocol(str, Enum):
    STANDARDIZED = "STANDARDIZED"
    PLAY_BASED = "PLAY_BASED"


class CompositeRecommendation(str, Enum):
    ELIGIBLE_RECOMMENDED = "ELIGIBLE_RECOMMENDED"
    NOT_ELIGIBLE_RECOMMENDED = "NOT_ELIGIBLE_RECOMMENDED"
    INDETERMINATE = "INDETERMINATE"


class TimelineCompliance(str, Enum):
    ON_TIME = "ON_TIME"
    AT_RISK = "AT_RISK"
    OVERDUE = "OVERDUE"


class EvaluationCaseStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    DOMAINS_COMPLETE = "DOMAINS_COMPLETE"
    REPORT_DRAFTED = "REPORT_DRAFTED"
    REVISIONS_REQUESTED = "REVISIONS_REQUESTED"
    ELIGIBILITY_DETERMINED = "ELIGIBILITY_DETERMINED"
    CANCELLED = "CANCELLED"


NON_TERMINAL_CASE_STATUSES: List[str] = [
    EvaluationCaseStatus.PLANNED.value,
    EvaluationCaseStatus.IN_PROGRESS.value,
    EvaluationCaseStatus.DOMAINS_COMPLETE.value,
    EvaluationCaseStatus.REPORT_DRAFTED.value,
    EvaluationCaseStatus.REVISIONS_REQUESTED.value,
]


class EvaluationCase(TypedDict):
    id: str
    referral_id: str
    child_id: str
    chair_provider_id: str
    assessment_protocol: Optional[str]
    required_domain_count: int
    completed_domain_count: int
    qualifying_domain_count: int
    max_weighted_percent_delay: Optional[float]
    composite_eligibility_recommendation: str
    recommended_weekly_minutes: int
    revision_round: int
    report_narrative_summary: Optional[str]
    report_drafted_at: Optional[str]
    last_revision_note: Optional[str]
    due_date: str
    timeline_compliance: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ------------------------------------------------------------- domain assessment
class DevelopmentalDomain(str, Enum):
    COGNITIVE = "COGNITIVE"
    COMMUNICATION = "COMMUNICATION"
    PHYSICAL_MOTOR = "PHYSICAL_MOTOR"
    SOCIAL_EMOTIONAL = "SOCIAL_EMOTIONAL"
    ADAPTIVE = "ADAPTIVE"


ALL_DOMAINS: List[str] = [d.value for d in DevelopmentalDomain]


class AssessmentMethod(str, Enum):
    STANDARDIZED = "STANDARDIZED"
    PLAY_BASED = "PLAY_BASED"
    OBSERVATION = "OBSERVATION"
    PARENT_REPORT = "PARENT_REPORT"


class DomainAssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class DomainAssessment(TypedDict):
    id: str
    evaluation_case_id: str
    evaluator_provider_id: str
    assessment_site_id: Optional[str]
    domain: str
    method: str
    window_start_utc: str
    window_end_utc: str
    chronological_age_months: int
    age_equivalent_months: Optional[int]
    standard_score: Optional[float]
    percent_delay: Optional[float]
    weighted_percent_delay: Optional[float]
    qualifies_delay: bool
    invalidation_reason: Optional[str]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ------------------------------------------------------------------ service plan
class EligibilityDecision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class DisabilityCategory(str, Enum):
    DEVELOPMENTAL_DELAY = "DEVELOPMENTAL_DELAY"
    SPEECH_OR_LANGUAGE_IMPAIRMENT = "SPEECH_OR_LANGUAGE_IMPAIRMENT"
    OTHER_HEALTH_IMPAIRMENT = "OTHER_HEALTH_IMPAIRMENT"


class ServiceSetting(str, Enum):
    COMMUNITY_PRESCHOOL = "COMMUNITY_PRESCHOOL"
    DISTRICT_ECSE_CLASSROOM = "DISTRICT_ECSE_CLASSROOM"
    HOME_BASED = "HOME_BASED"
    ITINERANT_ONLY = "ITINERANT_ONLY"


class KindergartenTransitionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    CONFERENCE_SCHEDULED = "CONFERENCE_SCHEDULED"
    PACKET_SENT = "PACKET_SENT"
    COMPLETE = "COMPLETE"


class TransitionAction(str, Enum):
    SCHEDULE_CONFERENCE = "SCHEDULE_CONFERENCE"
    SEND_PACKET = "SEND_PACKET"
    EXIT = "EXIT"


class ServicePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PARENT_CONSENT = "PENDING_PARENT_CONSENT"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    EXITED_TO_KINDERGARTEN = "EXITED_TO_KINDERGARTEN"
    SUPERSEDED = "SUPERSEDED"
    CLOSED_NOT_ELIGIBLE = "CLOSED_NOT_ELIGIBLE"


class ServicePlan(TypedDict):
    id: str
    evaluation_case_id: str
    child_id: str
    community_site_id: Optional[str]
    eligibility_decision: str
    disability_category: Optional[str]
    setting: Optional[str]
    override_justification: Optional[str]
    recommended_weekly_minutes: int
    assigned_weekly_minutes: int
    determined_by_user_id: str
    start_date: Optional[str]
    exit_date: Optional[str]
    kindergarten_transition_status: str
    transition_conference_date: Optional[str]
    receiving_school_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ------------------------------------------------------------------ service line
class ServiceLineDiscipline(str, Enum):
    SLP = "SLP"
    OT = "OT"
    PT = "PT"
    ECSE_TEACHER = "ECSE_TEACHER"
    SOCIAL_WORKER = "SOCIAL_WORKER"


class DeliveryModel(str, Enum):
    DIRECT = "DIRECT"
    CONSULT = "CONSULT"
    PUSH_IN = "PUSH_IN"


class ServiceLineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    STAFFED = "STAFFED"
    UNSTAFFED = "UNSTAFFED"
    DISCONTINUED = "DISCONTINUED"


class ServiceLine(TypedDict):
    id: str
    service_plan_id: str
    provider_id: Optional[str]
    delivery_site_id: Optional[str]
    discipline: str
    weekly_minutes: int
    delivery_model: str
    status: str
    created_at: str
    updated_at: str
    version: int
