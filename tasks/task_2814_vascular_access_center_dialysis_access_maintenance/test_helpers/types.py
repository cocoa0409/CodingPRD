"""Domain types for the vascular access centre API: status enums, role enum, entity TypedDicts.

Field names and enum members are taken verbatim from PRD.md.  Two resource kinds
(SurveillanceReading, RecoveryObservation) are immutable and therefore carry only
``id`` and ``created_at`` -- their TypedDicts deliberately omit ``updated_at``
and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    ACCESS_COORDINATOR = "AccessCoordinator"
    FACILITY_COORDINATOR = "FacilityCoordinator"
    INTERVENTIONALIST = "Interventionalist"
    SEDATION_RN = "SedationRN"
    CODER = "Coder"


# ─── Enumerations ─────────────────────────────────────────────────────────────

class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class PartnershipTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    WATCH = "WATCH"


class DialysisModality(str, Enum):
    IN_CENTER_HD = "IN_CENTER_HD"
    HOME_HD = "HOME_HD"
    PD = "PD"


class PayerProgram(str, Enum):
    BUNDLED_ESRD = "BUNDLED_ESRD"
    FEE_FOR_SERVICE = "FEE_FOR_SERVICE"


class AccessType(str, Enum):
    TUNNELED_CATHETER = "TUNNELED_CATHETER"
    AVF = "AVF"
    AVG = "AVG"


class Laterality(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class AccessSite(str, Enum):
    FOREARM = "FOREARM"
    UPPER_ARM = "UPPER_ARM"
    THIGH = "THIGH"
    INTERNAL_JUGULAR = "INTERNAL_JUGULAR"
    SUBCLAVIAN = "SUBCLAVIAN"


class VascularAccessStatus(str, Enum):
    PLANNED = "PLANNED"
    PLACED = "PLACED"
    MATURING = "MATURING"
    IN_USE = "IN_USE"
    DYSFUNCTIONAL = "DYSFUNCTIONAL"
    ABANDONED = "ABANDONED"


class ReadingKind(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class SuspectedProblem(str, Enum):
    STENOSIS = "STENOSIS"
    THROMBOSIS = "THROMBOSIS"
    CATHETER_DYSFUNCTION = "CATHETER_DYSFUNCTION"
    MATURATION_FAILURE = "MATURATION_FAILURE"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    TRIAGED = "TRIAGED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


class TriageVariant(str, Enum):
    TREND_BASED = "TREND_BASED"
    ABSOLUTE_BASED = "ABSOLUTE_BASED"


class Urgency(str, Enum):
    SAME_DAY = "SAME_DAY"
    NEXT_DAY = "NEXT_DAY"
    ROUTINE = "ROUTINE"


class HoldReason(str, Enum):
    COORDINATOR_REQUEST = "COORDINATOR_REQUEST"
    FACILITY_POSTURE_HOLD = "FACILITY_POSTURE_HOLD"


class RoomType(str, Enum):
    ANGIO_SUITE = "ANGIO_SUITE"
    PROCEDURE_ROOM = "PROCEDURE_ROOM"


class ClinicianRole(str, Enum):
    INTERVENTIONALIST = "INTERVENTIONALIST"
    SEDATION_RN = "SEDATION_RN"
    RECOVERY_RN = "RECOVERY_RN"
    CODER = "CODER"


class ProcedureType(str, Enum):
    ANGIOPLASTY = "ANGIOPLASTY"
    THROMBECTOMY = "THROMBECTOMY"
    CATHETER_EXCHANGE = "CATHETER_EXCHANGE"
    FISTULA_MATURATION_INTERVENTION = "FISTULA_MATURATION_INTERVENTION"


class SedationLevel(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"


class ProcedureClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_ROOM = "IN_ROOM"
    RECOVERY = "RECOVERY"
    DISCHARGED = "DISCHARGED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class ProcedureCodingStatus(str, Enum):
    UNCODED = "UNCODED"
    CODED = "CODED"
    ATTESTED = "ATTESTED"
    BILLED = "BILLED"
    DENIED = "DENIED"
    REBILLED = "REBILLED"


class ReimbursementVariant(str, Enum):
    BUNDLED_ESRD = "BUNDLED_ESRD"
    FEE_FOR_SERVICE = "FEE_FOR_SERVICE"


class CancelReason(str, Enum):
    COORDINATOR_CANCEL = "COORDINATOR_CANCEL"
    FACILITY_POSTURE_HOLD = "FACILITY_POSTURE_HOLD"


class DenialReason(str, Enum):
    MEDICAL_NECESSITY = "MEDICAL_NECESSITY"
    BUNDLING = "BUNDLING"
    DOCUMENTATION = "DOCUMENTATION"
    TIMELY_FILING = "TIMELY_FILING"


class CodeFamily(str, Enum):
    ANGIOPLASTY = "ANGIOPLASTY"
    THROMBECTOMY = "THROMBECTOMY"
    CATH_EXCHANGE = "CATH_EXCHANGE"
    IMAGING = "IMAGING"
    ACCESS_MAINTENANCE_BUNDLE = "ACCESS_MAINTENANCE_BUNDLE"


class CodeModifier(str, Enum):
    NONE = "NONE"
    M59 = "M59"
    M52 = "M52"


class DeviceType(str, Enum):
    SHEATH = "SHEATH"
    BALLOON = "BALLOON"
    STENT = "STENT"


class DeviceLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class DeviceUsageState(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class TargetAccessType(str, Enum):
    AVF = "AVF"
    AVG = "AVG"


class ConversionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    MATURATION_HOLD = "MATURATION_HOLD"
    CONVERTED = "CONVERTED"
    ABANDONED = "ABANDONED"


class InfectionEventType(str, Enum):
    ACCESS_SITE_INFECTION = "ACCESS_SITE_INFECTION"
    BACTEREMIA = "BACTEREMIA"


class ReadinessFailureReason(str, Enum):
    DIAMETER = "DIAMETER"
    FLOW = "FLOW"
    DEPTH = "DEPTH"
    MATURATION_DAYS = "MATURATION_DAYS"
    SURVEILLANCE_COUNT = "SURVEILLANCE_COUNT"


# ─── Entities carrying the full four-field common set ─────────────────────────

class DialysisFacility(TypedDict):
    id: str
    name: str
    facility_code: str
    contract_status: str
    partnership_tier: str
    partnership_score: int
    referral_volume_window: int
    raw_missed_count_window: int
    grace_credit_window: int
    adjusted_missed_count_window: int
    same_day_honored_window: int
    last_scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    dialysis_facility_id: str
    dialysis_modality: str
    payer_program: str
    access_count: int
    created_at: str
    updated_at: str
    version: int


class VascularAccess(TypedDict):
    id: str
    patient_id: str
    access_type: str
    laterality: str
    site: str
    placed_on: str
    predecessor_access_id: Optional[str]
    status: str
    angioplasty_count: int
    thrombectomy_count: int
    catheter_exchange_count: int
    maturation_intervention_count: int
    attributable_infection_count: int
    intervention_burden_score: int
    abandoned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    access_id: str
    referring_facility_id: str
    suspected_problem: str
    clinical_narrative: str
    missed_treatment_count: int
    status: str
    triage_score: Optional[int]
    triage_variant: Optional[str]
    urgency: Optional[str]
    triaged_at: Optional[str]
    completed_at: Optional[str]
    info_request_count: int
    hold_reason: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureRoom(TypedDict):
    id: str
    room_code: str
    room_type: str
    turnover_buffer_min: int
    daily_case_cap: int
    recovery_bay_count: int
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    clinician_role: str
    npi: str
    moderate_sedation_credentialed: bool
    credential_expires_on: Optional[str]
    max_concurrent_sedation_cases: int
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    referral_id: str
    access_id: str
    room_id: str
    primary_operator_id: str
    sedation_rn_id: Optional[str]
    attested_by_id: Optional[str]
    supporting_reading_id: Optional[str]
    procedure_type: str
    sedation_level: str
    scheduled_start: str
    scheduled_end: str
    clinical_status: str
    coding_status: str
    sedation_end_at: Optional[str]
    discharged_at: Optional[str]
    reimbursement_variant: Optional[str]
    allowed_amount_cents: int
    billed_amount_cents: int
    denied_amount_cents: int
    net_receivable_cents: int
    rebill_count: int
    medical_necessity_statement: Optional[str]
    abort_reason: Optional[str]
    cancel_reason: Optional[str]
    denial_reason: Optional[str]
    denial_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureCode(TypedDict):
    id: str
    procedure_id: str
    hcpcs_code: str
    code_family: str
    base_allowed_cents: int
    modifier: str
    rank: int
    is_bundled: bool
    reduction_factor_pct: int
    allowed_cents: int
    created_at: str
    updated_at: str
    version: int


class DeviceLot(TypedDict):
    id: str
    device_type: str
    catalog_code: str
    lot_number: str
    expires_on: str
    received_quantity: int
    quantity_on_hand: int
    quantity_reserved: int
    unit_cost_cents: int
    status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceUsage(TypedDict):
    id: str
    procedure_id: str
    device_lot_id: str
    quantity: int
    state: str
    wasted_quantity: int
    consumed_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessConversionPlan(TypedDict):
    id: str
    patient_id: str
    from_access_id: str
    target_access_id: Optional[str]
    target_access_type: str
    target_conversion_date: str
    status: str
    maturation_check_count: int
    last_check_at: Optional[str]
    last_diameter_mm: Optional[float]
    last_flow_ml_min: Optional[int]
    last_depth_mm: Optional[float]
    days_since_placement: Optional[int]
    readiness_met: bool
    readiness_failure_reasons: List[str]
    converted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InfectionEvent(TypedDict):
    id: str
    procedure_id: str
    access_id: str
    event_type: str
    organism: str
    onset_at: str
    days_post_procedure: int
    attributable: bool
    created_at: str
    updated_at: str
    version: int


# ─── Immutable records: id + created_at only ──────────────────────────────────

class SurveillanceReading(TypedDict):
    id: str
    access_id: str
    reported_by_facility_id: str
    reading_at: str
    access_flow_ml_min: int
    venous_pressure_mmhg: int
    recirculation_pct: float
    kind: str
    created_at: str


class RecoveryObservation(TypedDict):
    id: str
    procedure_id: str
    observed_at: str
    aldrete_score: int
    on_room_air: bool
    created_at: str
