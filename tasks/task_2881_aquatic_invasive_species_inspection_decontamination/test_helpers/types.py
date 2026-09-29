"""Domain types for the AIS inspection and decontamination program.

Entity TypedDicts, status enums and the role enum, derived from the PRD.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INSPECTOR = "Inspector"
    DECON_TECHNICIAN = "DeconTechnician"
    RELEASE_VERIFIER = "ReleaseVerifier"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    STATE_DATA_STEWARD = "StateDataSteward"
    TRAINING_OFFICER = "TrainingOfficer"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class WaterBodyClass(str, Enum):
    LAKE = "LAKE"
    RESERVOIR = "RESERVOIR"
    RIVER = "RIVER"
    CANAL = "CANAL"


class RiskTier(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class InfestationStatus(str, Enum):
    CLEAN = "CLEAN"
    SUSPECT = "SUSPECT"
    CONFIRMED_INFESTED = "CONFIRMED_INFESTED"


class StationType(str, Enum):
    WATERBODY_ACCESS = "WATERBODY_ACCESS"
    HIGHWAY_CORRIDOR = "HIGHWAY_CORRIDOR"


class StationStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StaffingLevel(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"


class InspectorStatus(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class CertificationLevel(str, Enum):
    TRAINEE = "TRAINEE"
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    DECON_CERTIFIED = "DECON_CERTIFIED"


class VesselType(str, Enum):
    OPEN_HULL = "OPEN_HULL"
    PONTOON_MULTI_CHAMBER = "PONTOON_MULTI_CHAMBER"
    BALLASTED_WAKEBOAT = "BALLASTED_WAKEBOAT"
    PERSONAL_WATERCRAFT = "PERSONAL_WATERCRAFT"


class WatchlistStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCHLISTED = "WATCHLISTED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InspectionStatus(str, Enum):
    INITIATED = "INITIATED"
    SCREENED = "SCREENED"
    PASSED = "PASSED"
    DECON_REQUIRED = "DECON_REQUIRED"
    DECON_COMPLETED = "DECON_COMPLETED"
    DECON_FAILED_ABANDONED = "DECON_FAILED_ABANDONED"
    REFUSED = "REFUSED"


class EnforcementStatus(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"
    CITED = "CITED"
    DISMISSED = "DISMISSED"


class ReferralReason(str, Enum):
    INSPECTION_REFUSAL = "INSPECTION_REFUSAL"
    QUARANTINE_RELEASE_FAILURE = "QUARANTINE_RELEASE_FAILURE"
    SEAL_TAMPER = "SEAL_TAMPER"
    DECON_EVASION = "DECON_EVASION"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class DeconOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    TREATED = "TREATED"
    RETREAT_REQUIRED = "RETREAT_REQUIRED"
    VERIFIED = "VERIFIED"
    ABANDONED = "ABANDONED"


class DryVerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    RETREAT = "RETREAT"
    ABANDON = "ABANDON"


class QuarantineOrderStatus(str, Enum):
    SEALED = "SEALED"
    RELEASE_REQUESTED = "RELEASE_REQUESTED"
    RELEASED = "RELEASED"
    VOIDED_BREACH = "VOIDED_BREACH"


class ReleaseOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DetectionClass(str, Enum):
    LIVE_ORGANISM = "LIVE_ORGANISM"
    DEAD_ORGANISM = "DEAD_ORGANISM"
    PLANT_FRAGMENT = "PLANT_FRAGMENT"


class DetectionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AcknowledgementVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    EVALUATED = "EVALUATED"
    CANCELLED = "CANCELLED"


class EvaluationMethod(str, Enum):
    PRE_POST = "PRE_POST"
    CONTROL_CORRIDOR = "CONTROL_CORRIDOR"


class Disposition(str, Enum):
    PASSED = "PASSED"
    DECON_REQUIRED = "DECON_REQUIRED"
    REFUSED = "REFUSED"


class EnforcementAction(str, Enum):
    REFER = "REFER"
    CITE = "CITE"
    DISMISS = "DISMISS"


# ---------------------------------------------------------------------------
# Entity shapes.  Rows carry id, created_at, updated_at and version, except
# TrainingRecord which is immutable and carries only id and created_at.
# ---------------------------------------------------------------------------
class WaterBody(TypedDict):
    id: str
    name: str
    state_code: str
    water_body_class: str
    risk_tier: str
    infestation_status: str
    downstream_of_water_body_id: Optional[str]
    detection_count: int
    live_detection_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionStation(TypedDict):
    id: str
    name: str
    station_type: str
    water_body_id: Optional[str]
    corridor_route_code: Optional[str]
    status: str
    mandatory_inspection: bool
    decon_bay_count: int
    hot_water_capable: bool
    seal_stock_initial_count: int
    seal_stock_count: int
    seals_in_circulation_count: int
    seals_retired_count: int
    certified_inspector_count: int
    decon_service_available: bool
    collected_fees_cents: int
    refunded_fees_cents: int
    campaign_allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class StationHours(TypedDict):
    id: str
    station_id: str
    opens_at: str
    closes_at: str
    staffing_level: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    home_station_id: str
    decon_endorsement: bool
    training_hours_total: float
    certification_level: str
    certification_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    """Immutable training log: only id and created_at accompany the fields."""
    id: str
    inspector_id: str
    module_code: str
    hours: float
    passed: bool
    completed_at: str
    created_at: str


class Watercraft(TypedDict):
    id: str
    registration_number: str
    home_state_code: str
    vessel_type: str
    hull_length_ft: float
    last_water_body_id: Optional[str]
    last_removed_at: Optional[str]
    compliance_strikes: int
    watchlist_status: str
    mandatory_decon_flag: bool
    last_decon_verified_at: Optional[str]
    quarantine_hold_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReciprocityAgreement(TypedDict):
    id: str
    partner_state_code: str
    honors_our_seals: bool
    max_seal_age_hours: int
    accepted_seal_prefix: str
    fee_waiver: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict):
    id: str
    station_id: str
    inspector_id: str
    watercraft_id: str
    prior_water_body_id: str
    honored_agreement_id: Optional[str]
    arrived_at: str
    residual_water_present: bool
    standing_water_ml: int
    presented_seal_number: Optional[str]
    presented_seal_state_code: Optional[str]
    presented_seal_issued_at: Optional[str]
    screening_completed_at: Optional[str]
    reciprocity_seal_honored: bool
    reciprocity_credit_points: int
    dry_credit_points: int
    risk_score: int
    advisory_risk_score: int
    risk_band: str
    decon_mandatory: bool
    quarantine_warranted: bool
    inspection_status: str
    enforcement_status: str
    referral_reason: Optional[str]
    agency_code: Optional[str]
    penalty_cents: int
    inspection_fee_cents: int
    decon_fee_cents: int
    surcharge_cents: int
    total_fee_cents: int
    fee_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class DeconOrder(TypedDict):
    id: str
    inspection_record_id: str
    station_id: str
    treated_by_inspector_id: Optional[str]
    verified_by_inspector_id: Optional[str]
    status: str
    attempt_count: int
    band_at_order: str
    water_temp_f: Optional[float]
    pressure_psi: Optional[float]
    dwell_seconds: Optional[int]
    treatment_started_at: Optional[str]
    treated_at: Optional[str]
    bay_released_at: Optional[str]
    treatment_effectiveness_pct: Optional[float]
    base_dry_hours: Optional[int]
    required_dry_hours: Optional[int]
    dry_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarantineOrder(TypedDict):
    id: str
    inspection_record_id: str
    watercraft_id: str
    station_id: str
    issued_by_inspector_id: str
    release_verified_by_inspector_id: Optional[str]
    seal_number: str
    seal_state_code: str
    status: str
    band_at_issue: str
    issued_at: str
    hold_hours_required: int
    hold_until: Optional[str]
    rejected_release_count: int
    created_at: str
    updated_at: str
    version: int


class DetectionReport(TypedDict):
    id: str
    inspection_record_id: str
    water_body_id: str
    reported_by_inspector_id: str
    species_code: str
    detection_class: str
    observed_at: str
    status: str
    submission_count: int
    state_db_ack_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationCampaign(TypedDict):
    id: str
    name: str
    target_water_body_id: str
    start_at: str
    end_at: str
    budget_cents: int
    impressions: int
    status: str
    evaluation_method: Optional[str]
    window_compliance_rate: Optional[float]
    baseline_compliance_rate: Optional[float]
    effectiveness_score: Optional[float]
    alternate_effectiveness_score: Optional[float]
    station_allocations: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
