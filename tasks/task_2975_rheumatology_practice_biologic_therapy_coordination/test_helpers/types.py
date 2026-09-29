"""Domain types for the Rheumatology Biologic Coordination API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RHEUMATOLOGIST = "Rheumatologist"
    PRIOR_AUTH_COORDINATOR = "PriorAuthCoordinator"
    PAYER_REVIEWER = "PayerReviewer"
    INFUSION_NURSE = "InfusionNurse"
    BENEFITS_COUNSELOR = "BenefitsCounselor"
    REGISTRY_ADMIN = "RegistryAdmin"
    PATIENT = "Patient"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Reference-data enums (PRD §3.1)
# --------------------------------------------------------------------------
class DiagnosisCode(str, Enum):
    RA_SEROPOSITIVE = "RA_SEROPOSITIVE"
    RA_SERONEGATIVE = "RA_SERONEGATIVE"
    PSA = "PSA"
    AXSPA = "AXSPA"


class ClinicianRoleType(str, Enum):
    RHEUMATOLOGIST = "RHEUMATOLOGIST"
    NURSE = "NURSE"


class MoleculeClass(str, Enum):
    TNFI = "TNFI"
    IL6 = "IL6"
    JAKI = "JAKI"
    CD20 = "CD20"
    CTLA4 = "CTLA4"


class DrugRoute(str, Enum):
    IV = "IV"
    SC = "SC"


class PanelType(str, Enum):
    CBC = "CBC"
    CMP = "CMP"
    LFT = "LFT"


class SiteOfCarePolicy(str, Enum):
    SITE_NEUTRAL = "SITE_NEUTRAL"
    PREFER_AMBULATORY = "PREFER_AMBULATORY"
    HOME_REQUIRED = "HOME_REQUIRED"


class ChairSiteType(str, Enum):
    HOSPITAL_OUTPATIENT = "HOSPITAL_OUTPATIENT"
    AMBULATORY_INFUSION_CENTER = "AMBULATORY_INFUSION_CENTER"


class ChairStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Visit and scoring enums (PRD §3.2)
# --------------------------------------------------------------------------
class VisitType(str, Enum):
    NEW = "NEW"
    FOLLOW_UP = "FOLLOW_UP"
    URGENT = "URGENT"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    SCORED = "SCORED"


class ScoringInstrument(str, Enum):
    CDAI = "CDAI"
    DAS28_CRP = "DAS28_CRP"


class ActivityCategory(str, Enum):
    REMISSION = "REMISSION"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class EscalationRecommendation(str, Enum):
    ESCALATE = "ESCALATE"
    OPTIMIZE_CURRENT = "OPTIMIZE_CURRENT"
    CONTINUE = "CONTINUE"


class TargetStatus(str, Enum):
    AT_TARGET = "AT_TARGET"
    NOT_AT_TARGET = "NOT_AT_TARGET"
    UNASSESSED = "UNASSESSED"


# --------------------------------------------------------------------------
# Screening enums (PRD §3.3)
# --------------------------------------------------------------------------
class ScreenType(str, Enum):
    TB_IGRA = "TB_IGRA"
    TB_TST = "TB_TST"
    TB_LTBI_TREATMENT_COMPLETE = "TB_LTBI_TREATMENT_COMPLETE"
    HBV_SURFACE_AG = "HBV_SURFACE_AG"
    HBV_CORE_AB = "HBV_CORE_AB"
    HCV_AB = "HCV_AB"


class ScreenResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INDETERMINATE = "INDETERMINATE"
    COMPLETED = "COMPLETED"


class TbScreenStatus(str, Enum):
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    INDETERMINATE = "INDETERMINATE"
    POSITIVE_UNTREATED = "POSITIVE_UNTREATED"
    CLEARED = "CLEARED"
    CLEARED_AFTER_TREATMENT = "CLEARED_AFTER_TREATMENT"


class HbvScreenStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    ACTIVE_INFECTION = "ACTIVE_INFECTION"
    OCCULT_RISK = "OCCULT_RISK"
    CLEARED = "CLEARED"


# --------------------------------------------------------------------------
# Therapy episode enums (PRD §2.9, §3.4, §3.9)
# --------------------------------------------------------------------------
class TherapyState(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    DISCONTINUED = "DISCONTINUED"


class FundingState(str, Enum):
    UNFUNDED = "UNFUNDED"
    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    LAPSED = "LAPSED"


class BenefitChannel(str, Enum):
    PHARMACY = "PHARMACY"
    MEDICAL = "MEDICAL"


class SiteOfCare(str, Enum):
    SELF_ADMIN = "SELF_ADMIN"
    AMBULATORY_INFUSION_CENTER = "AMBULATORY_INFUSION_CENTER"
    HOSPITAL_OUTPATIENT = "HOSPITAL_OUTPATIENT"
    HOME_INFUSION = "HOME_INFUSION"


class TrainingStatus(str, Enum):
    PENDING = "PENDING"
    NOT_REQUIRED = "NOT_REQUIRED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class HoldReason(str, Enum):
    SURGERY = "SURGERY"
    INFECTION = "INFECTION"
    LAB_ABNORMALITY = "LAB_ABNORMALITY"
    AUTH_LAPSE = "AUTH_LAPSE"
    PATIENT_REQUEST = "PATIENT_REQUEST"


class DiscontinuationReason(str, Enum):
    INADEQUATE_RESPONSE = "INADEQUATE_RESPONSE"
    INTOLERANCE = "INTOLERANCE"
    REMISSION_TAPER = "REMISSION_TAPER"
    PATIENT_REQUEST = "PATIENT_REQUEST"
    SAFETY_EVENT = "SAFETY_EVENT"
    SUPERSEDED = "SUPERSEDED"


class MonitoringStatus(str, Enum):
    CURRENT = "CURRENT"
    OVERDUE = "OVERDUE"


# --------------------------------------------------------------------------
# Authorization enums (PRD §3.5)
# --------------------------------------------------------------------------
class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Appointment enums (PRD §3.7)
# --------------------------------------------------------------------------
class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    PATIENT_REQUEST = "PATIENT_REQUEST"
    CLINIC_CLOSURE = "CLINIC_CLOSURE"
    SCHEDULING_ERROR = "SCHEDULING_ERROR"
    THERAPY_HELD = "THERAPY_HELD"


# --------------------------------------------------------------------------
# Assistance enrollment enums (PRD §3.8)
# --------------------------------------------------------------------------
class ProgramType(str, Enum):
    MANUFACTURER_COPAY_CARD = "MANUFACTURER_COPAY_CARD"
    FOUNDATION_GRANT = "FOUNDATION_GRANT"
    PATIENT_ASSISTANCE_PROGRAM = "PATIENT_ASSISTANCE_PROGRAM"


class EnrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    REAUTH_PENDING = "REAUTH_PENDING"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    FUNDING_DENIED = "FUNDING_DENIED"
    EPISODE_DISCONTINUED = "EPISODE_DISCONTINUED"
    PROGRAM_CLOSED = "PROGRAM_CLOSED"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# Resources carrying `updated_at` and `version` (PRD §2.4): Patient, Clinician,
# Drug, PayerPlan, InfusionChair, Visit, TherapyEpisode, Authorization,
# InfusionAppointment, AssistanceEnrollment.
#
# ScreeningRecord and MonitoringLab are append-only clinical documents and
# carry ONLY `id` and `created_at`.
# --------------------------------------------------------------------------
class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    diagnosis_code: str
    registry_consent: bool
    tb_screen_status: str
    hbv_screen_status: str
    target_status: str
    latest_activity_score: Optional[float]
    latest_activity_category: Optional[str]
    administered_dose_total: int
    active_episode_count: int
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    npi: str
    full_name: str
    role_type: str
    can_attest_formulary_exception: bool
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict):
    id: str
    name: str
    molecule_class: str
    route: str
    formulary_tier: int
    acquisition_cost_cents: int
    admin_time_minutes: int
    monitoring_panel_type: str
    monitoring_panel_interval_days: int
    tb_screen_required: bool
    hbv_screen_required: bool
    is_biosimilar: bool
    step_therapy_required_classes: List[str]
    created_at: str
    updated_at: str
    version: int


class PayerPlan(TypedDict):
    id: str
    name: str
    pharmacy_benefit_enabled: bool
    medical_benefit_enabled: bool
    site_of_care_policy: str
    coinsurance_pct: float
    deductible_remaining_cents: int
    medical_facility_fee_cents: int
    hospital_outpatient_multiplier: float
    appeal_rounds_allowed: int
    auth_validity_days: int
    step_therapy_classes_required: List[str]
    created_at: str
    updated_at: str
    version: int


class InfusionChair(TypedDict):
    id: str
    label: str
    site_type: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    patient_id: str
    clinician_id: str
    visit_datetime: str
    visit_end_datetime: str
    visit_type: str
    status: str
    scoring_instrument: Optional[str]
    tender_joint_count: Optional[int]
    swollen_joint_count: Optional[int]
    patient_global_assessment: Optional[float]
    physician_global_assessment: Optional[float]
    crp_mg_dl: Optional[float]
    esr_mm_hr: Optional[int]
    activity_score: Optional[float]
    activity_category: Optional[str]
    escalation_recommendation: Optional[str]
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningRecord(TypedDict):
    """Append-only clinical document: no `updated_at`, no `version`."""
    id: str
    patient_id: str
    screen_type: str
    result: str
    collected_at: str
    resulted_at: str
    recorded_by_user_id: str
    created_at: str


class TherapyEpisode(TypedDict):
    id: str
    patient_id: str
    drug_id: str
    payer_plan_id: str
    prior_episode_id: Optional[str]
    therapy_start_at: str
    line_of_therapy: int
    therapy_state: str
    funding_state: str
    benefit_channel: str
    site_of_care: str
    routing_frozen: bool
    self_injection_training_status: str
    self_injection_training_attempts: int
    hold_reason: Optional[str]
    held_at: Optional[str]
    resume_not_before: Optional[str]
    hold_count: int
    discontinuation_reason: Optional[str]
    discontinued_at: Optional[str]
    therapy_exposure_weeks: Optional[int]
    doses_administered: int
    monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    episode_id: str
    requested_units: int
    approved_units: Optional[int]
    units_reserved: int
    units_consumed: int
    units_remaining: Optional[int]
    status: str
    appeal_round: int
    formulary_exception_requested: bool
    hbv_prophylaxis_documented: bool
    unmet_step_therapy_classes: List[str]
    exception_attested_by_clinician_id: Optional[str]
    decision_reason: Optional[str]
    determination_at: Optional[str]
    valid_from: Optional[str]
    valid_through: Optional[str]
    submitted_at: Optional[str]
    benefit_channel: str
    created_at: str
    updated_at: str
    version: int


class MonitoringLab(TypedDict):
    """Append-only clinical document: no `updated_at`, no `version`."""
    id: str
    episode_id: str
    panel_type: str
    collected_at: str
    alt_u_l: Optional[float]
    neutrophil_k_ul: Optional[float]
    wbc_k_ul: Optional[float]
    alt_grade: int
    anc_grade: int
    abnormal_grade: int
    triggers_hold: bool
    recorded_by_user_id: str
    created_at: str


class InfusionAppointment(TypedDict):
    id: str
    episode_id: str
    chair_id: str
    scheduled_start: str
    scheduled_end: str
    dose_sequence: int
    status: str
    administered_at: Optional[str]
    cancellation_reason: Optional[str]
    reversal_reason: Optional[str]
    reserved_authorization_id: Optional[str]
    reserved_enrollment_id: Optional[str]
    dose_cost_share_cents: int
    assistance_applied_cents: int
    patient_out_of_pocket_cents: int
    created_at: str
    updated_at: str
    version: int


class AssistanceEnrollment(TypedDict):
    id: str
    episode_id: str
    program_type: str
    annual_benefit_cents: int
    benefit_used_cents: int
    benefit_reserved_cents: int
    benefit_remaining_cents: int
    coverage_start: str
    coverage_end: str
    reauth_due_at: str
    status: str
    termination_reason: Optional[str]
    submitted_by_user_id: str
    attested_by_user_id: Optional[str]
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
