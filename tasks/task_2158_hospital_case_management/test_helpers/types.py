"""Domain types for the Hospital Case Management & Discharge Planning API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Every one of the twelve resource types carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    UTILIZATION_REVIEW_NURSE = "UtilizationReviewNurse"
    PAYER_REPRESENTATIVE = "PayerRepresentative"
    POST_ACUTE_LIAISON = "PostAcuteLiaison"
    DISCHARGE_COORDINATOR = "DischargeCoordinator"


# --------------------------------------------------------------------------
# Episode (PRD §3.2, §3.3, §3.8, §3.9)
# --------------------------------------------------------------------------
class CaseStatus(str, Enum):
    ADMITTED = "ADMITTED"
    SCREENED = "SCREENED"
    PLANNING = "PLANNING"
    READY_FOR_DISCHARGE = "READY_FOR_DISCHARGE"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


class BarrierPosture(str, Enum):
    CLEAR = "CLEAR"
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"


class AdmissionType(str, Enum):
    EMERGENT = "EMERGENT"
    ELECTIVE = "ELECTIVE"
    OBSERVATION = "OBSERVATION"


class DischargeDisposition(str, Enum):
    HOME_SELF_CARE = "HOME_SELF_CARE"
    HOME_WITH_HH = "HOME_WITH_HH"
    SNF = "SNF"
    IRF = "IRF"
    LTACH = "LTACH"
    HOSPICE = "HOSPICE"
    AMA = "AMA"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class RiskVariant(str, Enum):
    ADMISSION_VARIANT = "ADMISSION_VARIANT"
    PREDISCHARGE_VARIANT = "PREDISCHARGE_VARIANT"


class ThroughputGrade(str, Enum):
    EXEMPLARY = "EXEMPLARY"
    ON_TARGET = "ON_TARGET"
    ABOVE_TARGET = "ABOVE_TARGET"
    OUTLIER = "OUTLIER"


class RevertReasonCode(str, Enum):
    CLINICAL_DETERIORATION = "CLINICAL_DETERIORATION"
    AUTH_LOST = "AUTH_LOST"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"
    FAMILY_WITHDREW = "FAMILY_WITHDREW"
    PATIENT_LEFT_AMA = "PATIENT_LEFT_AMA"


# --------------------------------------------------------------------------
# RiskScreening (PRD §3.2)
# --------------------------------------------------------------------------
class ScreeningType(str, Enum):
    ADMISSION = "ADMISSION"
    RESCREEN = "RESCREEN"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Barrier (PRD §3.3)
# --------------------------------------------------------------------------
class BarrierCode(str, Enum):
    HOUSING = "HOUSING"
    TRANSPORT = "TRANSPORT"
    INSURANCE_AUTH = "INSURANCE_AUTH"
    DME_DELIVERY = "DME_DELIVERY"
    GUARDIANSHIP = "GUARDIANSHIP"
    BEHAVIORAL = "BEHAVIORAL"
    FAMILY_DECISION = "FAMILY_DECISION"
    PHYSICIAN_ORDER = "PHYSICIAN_ORDER"
    BED_AVAILABILITY = "BED_AVAILABILITY"


class BarrierSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DelayReasonCode(str, Enum):
    AWAITING_BED = "AWAITING_BED"
    AWAITING_AUTH = "AWAITING_AUTH"
    AWAITING_DME = "AWAITING_DME"
    AWAITING_TRANSPORT = "AWAITING_TRANSPORT"
    AWAITING_FAMILY = "AWAITING_FAMILY"
    AWAITING_PHYSICIAN = "AWAITING_PHYSICIAN"
    CLINICAL_INSTABILITY = "CLINICAL_INSTABILITY"
    PATIENT_REFUSAL = "PATIENT_REFUSAL"


class BarrierStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class BarrierOrigin(str, Enum):
    MANUAL = "MANUAL"
    SCREENING_AUTO = "SCREENING_AUTO"
    AUTH_DENIAL_AUTO = "AUTH_DENIAL_AUTO"
    REVERT_AUTO = "REVERT_AUTO"


# --------------------------------------------------------------------------
# PostAcuteProvider (PRD §3.1)
# --------------------------------------------------------------------------
class ProviderType(str, Enum):
    SNF = "SNF"
    HOME_HEALTH = "HOME_HEALTH"
    IRF = "IRF"
    LTACH = "LTACH"
    DME_SUPPLIER = "DME_SUPPLIER"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# --------------------------------------------------------------------------
# Referral / BedOffer (PRD §3.4, §3.5)
# --------------------------------------------------------------------------
class LevelOfCare(str, Enum):
    SNF = "SNF"
    HOME_HEALTH = "HOME_HEALTH"
    IRF = "IRF"
    LTACH = "LTACH"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    BROADCAST = "BROADCAST"
    CHOICE_PENDING = "CHOICE_PENDING"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ChoiceBasis(str, Enum):
    PATIENT_PREFERENCE = "PATIENT_PREFERENCE"
    FAMILY_PREFERENCE = "FAMILY_PREFERENCE"
    CLINICAL_MATCH = "CLINICAL_MATCH"
    ONLY_AVAILABLE = "ONLY_AVAILABLE"


class BedOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED_BY_PATIENT = "ACCEPTED_BY_PATIENT"
    DECLINED_BY_PATIENT = "DECLINED_BY_PATIENT"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class RateVariant(str, Enum):
    NETWORK_RATE = "NETWORK_RATE"
    BILLED_RATE = "BILLED_RATE"


# --------------------------------------------------------------------------
# AuthorizationRequest (PRD §3.6)
# --------------------------------------------------------------------------
class AuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AuthorizationDecision(str, Enum):
    PEND = "PEND"
    APPROVE = "APPROVE"
    PARTIAL = "PARTIAL"
    DENY = "DENY"


class DenialReason(str, Enum):
    NOT_MEDICALLY_NECESSARY = "NOT_MEDICALLY_NECESSARY"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"
    INCOMPLETE_CLINICALS = "INCOMPLETE_CLINICALS"


# --------------------------------------------------------------------------
# TransportVehicle / LogisticsOrder (PRD §3.1, §3.7)
# --------------------------------------------------------------------------
class VehicleType(str, Enum):
    WHEELCHAIR_VAN = "WHEELCHAIR_VAN"
    BLS_AMBULANCE = "BLS_AMBULANCE"
    ALS_AMBULANCE = "ALS_AMBULANCE"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class OrderType(str, Enum):
    PATIENT_TRANSPORT = "PATIENT_TRANSPORT"
    DME_DELIVERY = "DME_DELIVERY"


class ItemCode(str, Enum):
    HOSPITAL_BED = "HOSPITAL_BED"
    OXYGEN_CONCENTRATOR = "OXYGEN_CONCENTRATOR"
    WHEELCHAIR = "WHEELCHAIR"
    WALKER = "WALKER"
    CPAP = "CPAP"


class LogisticsStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    CLINICAL_CHANGE = "CLINICAL_CHANGE"
    VEHICLE_UNAVAILABLE = "VEHICLE_UNAVAILABLE"
    READINESS_REVERTED = "READINESS_REVERTED"
    USER_REQUEST = "USER_REQUEST"


# ==========================================================================
# Entity shapes — all twelve carry id / created_at / updated_at / version
# ==========================================================================
class Payer(TypedDict):
    id: str
    name: str
    snf_auth_required: bool
    hh_auth_required: bool
    coinsurance_pct: float
    auth_expiry_days: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    primary_payer_id: str
    prior_admissions_180d: int
    lives_alone: bool
    has_pcp: bool
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    patient_id: str
    admission_type: str
    drg_code: str
    drg_gmlos_days: float
    attending_unit: str
    admitted_at: str
    assigned_case_manager_id: str
    case_status: str
    barrier_posture: str
    discharge_disposition: Optional[str]
    current_risk_score: int
    current_risk_band: str
    risk_variant_applied: str
    barriers_ever_opened_count: int
    pcp_followup_booked: bool
    med_reconciliation_completed: bool
    tcm_call_scheduled: bool
    home_monitoring_enrolled: bool
    readmission_bundle_complete: bool
    logistics_committed_cents: int
    authorized_days_total: int
    avoidable_delay_hours: float
    los_hours: float
    adjusted_los_hours: float
    expected_los_hours: float
    observed_expected_ratio: float
    throughput_grade: str
    marked_ready_by_user_id: Optional[str]
    marked_ready_at: Optional[str]
    discharged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskScreening(TypedDict):
    id: str
    episode_id: str
    screening_type: str
    functional_score: int
    cognitive_score: int
    social_support_score: int
    medication_count: int
    prior_admissions_snapshot: int
    lives_alone_snapshot: bool
    has_pcp_snapshot: bool
    variant_applied: str
    composite_risk_score: int
    risk_band: str
    status: str
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Barrier(TypedDict):
    id: str
    episode_id: str
    barrier_code: str
    severity: str
    delay_reason_code: str
    avoidable: bool
    status: str
    clock_start_at: str
    clock_stop_at: Optional[str]
    accrued_delay_minutes: int
    reopen_count: int
    opened_by_user_id: str
    origin: str
    created_at: str
    updated_at: str
    version: int


class PostAcuteProvider(TypedDict):
    id: str
    name: str
    provider_type: str
    quality_star_rating: int
    distance_miles_from_hospital: int
    bed_unit_codes: List[str]
    status: str
    held_bed_units: int
    offers_received_count: int
    offers_submitted_count: int
    offers_accepted_count: int
    acceptance_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class NetworkContract(TypedDict):
    id: str
    payer_id: str
    provider_id: str
    in_network: bool
    negotiated_daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    episode_id: str
    requested_level_of_care: str
    projected_stay_days: int
    needed_by: str
    round_index: int
    broadcast_provider_ids: List[str]
    status: str
    chosen_bed_offer_id: Optional[str]
    choice_basis: Optional[str]
    patient_choice_attested: bool
    recommended_bed_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BedOffer(TypedDict):
    id: str
    referral_id: str
    provider_id: str
    round_index: int
    bed_unit_code: str
    bed_available_from: str
    hold_expires_at: str
    daily_rate_cents: int
    status: str
    rank_score: int
    rate_variant_applied: str
    projected_gross_cents: int
    projected_patient_share_cents: int
    projected_plan_share_cents: int
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict):
    id: str
    episode_id: str
    payer_id: str
    provider_id: str
    level_of_care: str
    requested_days: int
    billed_daily_rate_cents: int
    approved_days: Optional[int]
    appeal_round: int
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    expires_at: Optional[str]
    rate_variant_applied: str
    gross_projection_cents: int
    volume_discount_pct: float
    authorized_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class TransportVehicle(TypedDict):
    id: str
    operator_name: str
    vehicle_type: str
    base_rate_cents: int
    per_mile_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LogisticsOrder(TypedDict):
    id: str
    episode_id: str
    order_type: str
    vehicle_id: Optional[str]
    supplier_provider_id: Optional[str]
    destination_provider_id: Optional[str]
    item_code: Optional[str]
    mileage_miles: Optional[int]
    window_start: str
    window_end: str
    cost_cents: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
