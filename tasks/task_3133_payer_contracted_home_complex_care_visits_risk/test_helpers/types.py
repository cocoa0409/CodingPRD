"""Domain types: entity shapes, status enums, role enum.

Derived from the PRD's entity narratives (section 3) and endpoint table (section 4).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"
    ENGAGEMENT_SPECIALIST = "EngagementSpecialist"
    CARE_COORDINATOR = "CareCoordinator"
    CLINICIAN = "Clinician"
    PERFORMANCE_ANALYST = "PerformanceAnalyst"


class PaymentModel(str, Enum):
    CAPITATED = "CAPITATED"
    SHARED_SAVINGS = "SHARED_SAVINGS"


class Discipline(str, Enum):
    NP = "NP"
    SW = "SW"
    BH = "BH"


class ClinicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class OutreachChannel(str, Enum):
    PHONE = "PHONE"
    MAIL = "MAIL"
    IN_PERSON = "IN_PERSON"
    PCP_REFERRAL = "PCP_REFERRAL"


class EnrollmentStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    OUTREACH = "OUTREACH"
    CONSENTED = "CONSENTED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    DISENROLLED = "DISENROLLED"


class DisenrollmentReason(str, Enum):
    MEMBER_REQUEST = "MEMBER_REQUEST"
    PAYER_TERMINATION = "PAYER_TERMINATION"
    DECEASED = "DECEASED"
    MOVED_OUT_OF_AREA = "MOVED_OUT_OF_AREA"
    NON_ENGAGEMENT = "NON_ENGAGEMENT"


class CareTeamStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class VisitType(str, Enum):
    INITIAL_ASSESSMENT = "INITIAL_ASSESSMENT"
    ROUTINE_FOLLOWUP = "ROUTINE_FOLLOWUP"
    URGENT = "URGENT"
    POST_ED_FOLLOWUP = "POST_ED_FOLLOWUP"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancellationReason(str, Enum):
    MEMBER_REQUEST = "MEMBER_REQUEST"
    CLINICIAN_UNAVAILABLE = "CLINICIAN_UNAVAILABLE"
    MEMBER_NO_SHOW = "MEMBER_NO_SHOW"
    ENROLLMENT_ENDED = "ENROLLMENT_ENDED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class TriggerSource(str, Enum):
    MEMBER_CALL = "MEMBER_CALL"
    PCP_ALERT = "PCP_ALERT"
    PLAN_ALERT = "PLAN_ALERT"
    POST_ED_DISCHARGE = "POST_ED_DISCHARGE"


class EpisodeStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    DISPATCHED = "DISPATCHED"
    ON_SCENE = "ON_SCENE"
    RESOLVED = "RESOLVED"
    LAPSED = "LAPSED"


class ResolvedOutcome(str, Enum):
    AVOIDED_ED = "AVOIDED_ED"
    REFERRED_TO_ED = "REFERRED_TO_ED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class CareProgram(TypedDict, total=False):
    id: str
    program_code: str
    display_name: str
    service_geography_zips: List[str]
    urgent_response_sla_hours: int
    current_period_index: int
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict, total=False):
    id: str
    care_program_id: str
    payer_name: str
    contract_effective_date: str
    contract_expiration_date: str
    payment_model: str
    pmpm_rate_cents: Optional[int]
    shared_savings_baseline_pmpm_cents: Optional[int]
    shared_savings_split_pct: Optional[float]
    quality_withhold_pct: float
    min_performance_threshold: float
    created_at: str
    updated_at: str
    version: int


class PCPProvider(TypedDict, total=False):
    id: str
    care_program_id: str
    npi: str
    full_name: str
    practice_name: str
    notification_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict, total=False):
    id: str
    care_program_id: str
    full_name: str
    discipline: str
    home_zip: str
    max_daily_visits: int
    active_daily_visit_count: int
    urgent_response_qualified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    care_program_id: str
    payer_contract_id: str
    member_external_id: str
    full_name: str
    date_of_birth: str
    address_zip: str
    pcp_provider_id: str
    chronic_condition_codes: List[str]
    prior_ed_visits_12mo: int
    prior_inpatient_admits_12mo: int
    burden_score_provisional: int
    burden_score_final: Optional[int]
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class MemberEnrollment(TypedDict, total=False):
    id: str
    member_id: str
    outreach_channel: str
    outreach_attempts: int
    consent_recorded_at: Optional[str]
    consent_document_id: Optional[str]
    disenrollment_reason: Optional[str]
    status: str
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class CareTeam(TypedDict, total=False):
    id: str
    enrollment_id: str
    member_id: str
    primary_np_id: Optional[str]
    social_worker_id: Optional[str]
    behavioral_clinician_id: Optional[str]
    status: str
    composition_complete: bool
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    enrollment_id: str
    member_id: str
    clinician_id: str
    visit_type: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    cancellation_reason: Optional[str]
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitAssessment(TypedDict, total=False):
    id: str
    visit_id: str
    member_id: str
    medication_reconciliation: Dict[str, Any]
    safety_evaluation: Dict[str, Any]
    social_needs_screening: Dict[str, Any]
    pcp_coordination_note: str
    pcp_notified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class UrgentResponseEpisode(TypedDict, total=False):
    id: str
    enrollment_id: str
    member_id: str
    trigger_source: str
    triggered_at: str
    sla_deadline: str
    dispatched_clinician_id: Optional[str]
    on_scene_at: Optional[str]
    resolved_outcome: Optional[str]
    sla_met: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceMeasurement(TypedDict, total=False):
    id: str
    payer_contract_id: str
    member_id: str
    period_index: int
    urgent_episodes_triggered: int
    urgent_episodes_sla_met: int
    urgent_episodes_avoided_ed: int
    visits_completed: int
    visits_no_show: int
    visits_cancelled: int
    pcp_coordination_rate: float
    composite_score: float
    created_at: str
    updated_at: str
    version: int


class PayerSettlement(TypedDict, total=False):
    id: str
    payer_contract_id: str
    period_index: int
    enrolled_member_count: int
    gross_capitation_cents: Optional[int]
    gross_savings_share_cents: Optional[int]
    quality_withhold_cents: int
    withhold_released_cents: Optional[int]
    net_payment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalCost(TypedDict, total=False):
    id: str
    payer_contract_id: str
    member_id: str
    period_index: int
    amount_cents: int
    incurred_date: str
    created_at: str
    updated_at: str
    version: int
