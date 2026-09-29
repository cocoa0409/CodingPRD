"""Domain types for the Shellfish Harvest Classification API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1) — exactly five, spelled precisely
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SHELLFISH_CONTROL_AUTHORITY = "ShellfishControlAuthority"
    SITING_REVIEWER = "SitingReviewer"
    FARM_OPERATOR = "FarmOperator"
    HATCHERY_OPERATOR = "HatcheryOperator"
    SEAFOOD_DEALER = "SeafoodDealer"


# --------------------------------------------------------------------------
# Growing area — the two orthogonal status dimensions (PRD §3.1)
# --------------------------------------------------------------------------
class AreaClassification(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"


class AreaHarvestStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_RAINFALL = "CLOSED_RAINFALL"
    CLOSED_SAMPLE_FAILURE = "CLOSED_SAMPLE_FAILURE"


class EligibleClassification(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"


class StatisticsVariant(str, Enum):
    SYSTEMATIC_RANDOM = "SYSTEMATIC_RANDOM"
    ADVERSE_CONDITION = "ADVERSE_CONDITION"


class SampleStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Lease (PRD §3.4)
# --------------------------------------------------------------------------
class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PENDING_DECISION = "PENDING_DECISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClearanceState(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    OBJECTION = "OBJECTION"


class ReviewDecision(str, Enum):
    CLEARED = "CLEARED"
    OBJECTION = "OBJECTION"


class LeaseDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class GearType(str, Enum):
    BOTTOM = "BOTTOM"
    RACK_AND_BAG = "RACK_AND_BAG"
    FLOATING_BAG = "FLOATING_BAG"


# --------------------------------------------------------------------------
# Seed (PRD §3.5)
# --------------------------------------------------------------------------
class Species(str, Enum):
    CRASSOSTREA_VIRGINICA = "CRASSOSTREA_VIRGINICA"
    MERCENARIA_MERCENARIA = "MERCENARIA_MERCENARIA"
    MYTILUS_EDULIS = "MYTILUS_EDULIS"


class SeedLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED = "SCREENED"
    NURSERY = "NURSERY"
    READY_FOR_PLANTING = "READY_FOR_PLANTING"
    PLANTED = "PLANTED"
    REJECTED = "REJECTED"


class ScreeningResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class NurserySystem(str, Enum):
    UPWELLER = "UPWELLER"
    FLOAT_UPWELLER = "FLOAT_UPWELLER"
    RACK = "RACK"


# --------------------------------------------------------------------------
# Grow-out gear and husbandry (PRD §3.6)
# --------------------------------------------------------------------------
class GrowoutUnitStatus(str, Enum):
    DEPLOYED = "DEPLOYED"
    HARVESTING = "HARVESTING"
    RETRIEVED = "RETRIEVED"
    VOIDED = "VOIDED"


class GrowoutVoidReason(str, Enum):
    OPERATOR_CORRECTION = "OPERATOR_CORRECTION"
    SEED_LOT_REJECTED = "SEED_LOT_REJECTED"


class HusbandryLogType(str, Enum):
    INSPECTION = "INSPECTION"
    PREDATOR_CONTROL = "PREDATOR_CONTROL"
    DENSITY_THINNING = "DENSITY_THINNING"
    GEAR_MAINTENANCE = "GEAR_MAINTENANCE"


class PredatorSpecies(str, Enum):
    OYSTER_DRILL = "OYSTER_DRILL"
    BLUE_CRAB = "BLUE_CRAB"
    COWNOSE_RAY = "COWNOSE_RAY"
    SEA_STAR = "SEA_STAR"


class ControlMethod(str, Enum):
    NETTING = "NETTING"
    TRAPPING = "TRAPPING"
    MANUAL_REMOVAL = "MANUAL_REMOVAL"
    FENCING = "FENCING"


# --------------------------------------------------------------------------
# Vessels and authorizations (PRD §3.7)
# --------------------------------------------------------------------------
class RefrigerationType(str, Enum):
    NONE = "NONE"
    ICE_SLURRY = "ICE_SLURRY"
    MECHANICAL = "MECHANICAL"


class AuthorizationStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class AuthorizationVoidReason(str, Enum):
    AREA_CLOSURE = "AREA_CLOSURE"
    SEED_LOT_REJECTED = "SEED_LOT_REJECTED"


# --------------------------------------------------------------------------
# Harvest lots (PRD §3.8)
# --------------------------------------------------------------------------
class LotStatus(str, Enum):
    HARVESTED = "HARVESTED"
    TAGGED = "TAGGED"
    SHIPPED = "SHIPPED"
    EMBARGOED = "EMBARGOED"
    RECALLED = "RECALLED"
    VOIDED = "VOIDED"


class TttBasisVariant(str, Enum):
    FIRST_HARVEST_BASIS = "FIRST_HARVEST_BASIS"
    LAST_HARVEST_BASIS = "LAST_HARVEST_BASIS"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


class LotEmbargoReason(str, Enum):
    AREA_CLOSURE = "AREA_CLOSURE"


class LotVoidReason(str, Enum):
    OPERATOR_CORRECTION = "OPERATOR_CORRECTION"


# --------------------------------------------------------------------------
# Dealers, shipments, investigations, vibrio plans (PRD §3.9, §3.8)
# --------------------------------------------------------------------------
class CertificationCategory(str, Enum):
    SHELLSTOCK_SHIPPER = "SHELLSTOCK_SHIPPER"
    SHUCKER_PACKER = "SHUCKER_PACKER"
    REPACKER = "REPACKER"
    DEPURATION_PROCESSOR = "DEPURATION_PROCESSOR"


class ListingStatus(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    AUTHORITY_ACTION = "AUTHORITY_ACTION"
    RECALL_STRIKES = "RECALL_STRIKES"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    SHIPPED = "SHIPPED"
    HELD = "HELD"
    RECALLED = "RECALLED"


class ShipmentHeldReason(str, Enum):
    LOT_EMBARGO = "LOT_EMBARGO"
    DEALER_SUSPENSION = "DEALER_SUSPENSION"


class ShipmentRecallReason(str, Enum):
    ILLNESS_TRACEBACK = "ILLNESS_TRACEBACK"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    TRACEBACK = "TRACEBACK"
    CONFIRMED = "CONFIRMED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class ScopeVariant(str, Enum):
    NARROW = "NARROW"
    BROAD = "BROAD"


class Pathogen(str, Enum):
    VIBRIO_PARAHAEMOLYTICUS = "VIBRIO_PARAHAEMOLYTICUS"
    VIBRIO_VULNIFICUS = "VIBRIO_VULNIFICUS"
    NOROVIRUS = "NOROVIRUS"
    SALMONELLA = "SALMONELLA"


class VibrioPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity shapes (PRD §2.4). Resources carrying the full quartet declare
# id/created_at/updated_at/version; the three append-only event records
# (HusbandryLog, WaterSample, RainfallEvent) declare only id and created_at.
# --------------------------------------------------------------------------
class GrowingArea(TypedDict):
    id: str
    code: str
    water_body: str
    classification: str
    harvest_status: str
    rainfall_closure_threshold_in: float
    rainfall_closure_hours: int
    reopen_sample_count_required: int
    clean_sample_mpn_limit: float
    conditional_management_plan_on_file: bool
    last_closure_started_at: Optional[str]
    closure_reopen_eligible_at: Optional[str]
    consecutive_clean_samples: int
    accepted_sample_count: int
    geometric_mean_mpn: Optional[float]
    p90_mpn: Optional[float]
    eligible_classification: str
    open_authorization_count: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    growing_area_id: str
    operator_user_id: str
    lease_code: str
    requested_acreage: float
    plot_codes: List[str]
    gear_types_permitted: List[str]
    authorized_gear_units: int
    deployed_gear_units: int
    status: str
    navigation_clearance: str
    environmental_clearance: str
    navigation_reviewer_user_id: Optional[str]
    environmental_reviewer_user_id: Optional[str]
    revision_round: int
    rent_paid_through_date: Optional[str]
    royalty_accrued_cents: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hatchery(TypedDict):
    id: str
    name: str
    state_code: str
    ncsp_certificate_no: str
    certificate_expires_on: str
    pathogen_free_species: List[str]
    created_at: str
    updated_at: str
    version: int


class SeedLot(TypedDict):
    id: str
    hatchery_id: str
    lease_id: str
    species: str
    received_seed_count: int
    disease_certificate_no: str
    disease_cert_issued_on: str
    shipped_on: str
    status: str
    screening_result: Optional[str]
    screened_on: Optional[str]
    nursery_started_on: Optional[str]
    nursery_system: Optional[str]
    nursery_completed_on: Optional[str]
    surviving_seed_count: Optional[int]
    survival_rate_pct: Optional[float]
    allocated_seed_count: int
    unallocated_seed_count: int
    created_at: str
    updated_at: str
    version: int


class GrowoutUnit(TypedDict):
    id: str
    lease_id: str
    seed_lot_id: str
    plot_code: str
    gear_type: str
    gear_units: int
    seed_count_planted: int
    deployed_on: str
    planned_retrieval_on: str
    status: str
    retrieved_on: Optional[str]
    void_reason: Optional[str]
    last_inspection_at: Optional[str]
    last_predator_control_at: Optional[str]
    husbandry_current: bool
    mortality_count_total: int
    created_at: str
    updated_at: str
    version: int


class HusbandryLog(TypedDict):
    """Append-only journal record — no updated_at, no version (PRD §2.4)."""
    id: str
    growout_unit_id: str
    log_type: str
    performed_at: str
    performed_by_user_id: str
    predator_species: Optional[str]
    control_method: Optional[str]
    mortality_count: int
    notes: Optional[str]
    created_at: str


class WaterSample(TypedDict):
    """Append-only monitoring record — no updated_at, no version (PRD §2.4)."""
    id: str
    growing_area_id: str
    station_code: str
    collected_at: str
    fecal_coliform_mpn: float
    water_temp_c: float
    salinity_ppt: Optional[float]
    sample_status: str
    is_adverse_condition: bool
    counted_clean: bool
    created_at: str


class RainfallEvent(TypedDict):
    """Append-only monitoring record — no updated_at, no version (PRD §2.4)."""
    id: str
    growing_area_id: str
    gauge_code: str
    observed_at: str
    inches_24h: float
    triggered_closure: bool
    voided_authorization_count: int
    created_at: str


class HarvestVessel(TypedDict):
    id: str
    name: str
    registration_no: str
    refrigeration_type: str
    concurrent_authorization_capacity: int
    active_authorization_count: int
    created_at: str
    updated_at: str
    version: int


class HarvestAuthorization(TypedDict):
    id: str
    lease_id: str
    growout_unit_id: str
    vessel_id: str
    dealer_id: str
    growing_area_id: str
    window_start: str
    window_end: str
    projected_bushels: int
    harvested_bushels: int
    status: str
    harvest_start_at: Optional[str]
    harvest_end_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict):
    id: str
    harvest_authorization_id: str
    dealer_id: str
    shipment_id: Optional[str]
    lot_code: str
    bushels: int
    first_out_of_water_at: str
    last_out_of_water_at: str
    placed_in_temperature_control_at: str
    water_temp_c: float
    ttt_minutes_first_basis: int
    ttt_minutes_last_basis: int
    ttt_basis_variant: str
    governing_ttt_minutes: int
    allowed_ttt_minutes: int
    vibrio_control_plan_id: str
    vibrio_plan_month: int
    compliance_status: str
    status: str
    tag_harvest_date: Optional[str]
    tag_area_code: Optional[str]
    tag_lease_code: Optional[str]
    tag_dealer_certification_no: Optional[str]
    season_total_bushels_at_creation: int
    royalty_rate_cents_per_bushel: int
    royalty_cents: int
    inspection_fee_cents: int
    conservation_surcharge_cents: int
    lot_settlement_cents: int
    embargo_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    name: str
    state_code: str
    certification_category: str
    certification_no: str
    certified_through: str
    icssl_listed_through: Optional[str]
    listing_status: str
    recall_strike_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    dealer_id: str
    destination_state: str
    carrier: str
    lot_ids: List[str]
    lot_count: int
    total_bushels: int
    is_interstate: bool
    status: str
    shipped_at: Optional[str]
    held_reason: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IllnessInvestigation(TypedDict):
    id: str
    source_shipment_id: str
    reported_at: str
    illness_count: int
    pathogen: str
    scope_variant: Optional[str]
    status: str
    traced_lot_ids: List[str]
    traced_lot_count: int
    recalled_shipment_count: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VibrioControlPlan(TypedDict):
    id: str
    season_month: int
    max_time_to_temperature_minutes: int
    high_water_temp_c: float
    high_temp_reduction_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassificationSummary(TypedDict):
    variant: str
    sample_count: int
    mean_log10: Optional[float]
    geometric_mean_mpn: Optional[float]
    p90_mpn: Optional[float]
    eligible_classification: str
    window_start_at: Optional[str]
    window_end_at: Optional[str]
