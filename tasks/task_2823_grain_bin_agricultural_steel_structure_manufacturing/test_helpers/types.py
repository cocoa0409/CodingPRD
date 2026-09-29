"""Domain types for the grain bin manufacturing API.

Status enums, the role enum and one TypedDict per stored entity.

Five entities are immutable reference or derived data and carry ONLY `id` and
`created_at` — no `updated_at` and no `version` (PRD 2.5): Jurisdiction,
GrainProfile, CoatingSpec, RollFormingLine and KitLine.  Their TypedDicts omit
both properties deliberately.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    DESIGN_ENGINEER = "DesignEngineer"
    SEALING_ENGINEER = "SealingEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    DEALER_PRINCIPAL = "DealerPrincipal"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    QUALITY_INSPECTOR = "QualityInspector"


class EngineerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class BinDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    SEALED = "SEALED"
    RECALLED = "RECALLED"


class DesignMethod(str, Enum):
    ASD = "ASD"
    LRFD = "LRFD"


class GoverningLoadCase(str, Enum):
    GRAIN_LATERAL = "GRAIN_LATERAL"
    WIND_UPLIFT = "WIND_UPLIFT"
    SEISMIC_BASE_SHEAR = "SEISMIC_BASE_SHEAR"


class AnalysisVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CoilLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class RollFormingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class OrderProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    KITTED = "KITTED"
    SHIPPED = "SHIPPED"
    HOLD_CREDIT = "HOLD_CREDIT"
    HOLD_ENGINEERING = "HOLD_ENGINEERING"
    CANCELLED = "CANCELLED"


class OrderFinancialStatus(str, Enum):
    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class InstallationReadiness(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    BLOCKED = "BLOCKED"


class OrderSeason(str, Enum):
    PRESEASON = "PRESEASON"
    HARVEST_PEAK = "HARVEST_PEAK"
    OFFSEASON = "OFFSEASON"


class AerationPackage(str, Enum):
    NONE = "NONE"
    AERATION = "AERATION"
    DRYING_FULL = "DRYING_FULL"


class UnloadSystem(str, Enum):
    GRAVITY = "GRAVITY"
    SWEEP_AUGER = "SWEEP_AUGER"
    POWER_SWEEP = "POWER_SWEEP"


class TrailerType(str, Enum):
    FLATBED = "FLATBED"
    HIGH_CUBE_VAN = "HIGH_CUBE_VAN"
    STEP_DECK = "STEP_DECK"


class AllocationBasis(str, Enum):
    WEIGHT = "WEIGHT"
    CUBE = "CUBE"


class FreightLoadStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CrewStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class CertificationTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class FieldFailureStatus(str, Enum):
    INTAKE = "INTAKE"
    ANALYSIS_IN_PROGRESS = "ANALYSIS_IN_PROGRESS"
    DETERMINED = "DETERMINED"


class FailureMode(str, Enum):
    SIDEWALL_BUCKLE = "SIDEWALL_BUCKLE"
    ROOF_COLLAPSE = "ROOF_COLLAPSE"
    CORROSION_PERFORATION = "CORROSION_PERFORATION"
    ANCHOR_PULLOUT = "ANCHOR_PULLOUT"


class StructuralVerdict(str, Enum):
    WITHIN_DESIGN = "WITHIN_DESIGN"
    EXCEEDS_DESIGN = "EXCEEDS_DESIGN"


class CorrosionVerdict(str, Enum):
    WITHIN_CLASS = "WITHIN_CLASS"
    EXCEEDS_CLASS = "EXCEEDS_CLASS"


class DeterminedCause(str, Enum):
    STRUCTURAL_UNDERDESIGN = "STRUCTURAL_UNDERDESIGN"
    COATING_INADEQUATE = "COATING_INADEQUATE"
    INSTALLATION_DEFECT = "INSTALLATION_DEFECT"
    OVERLOAD_MISUSE = "OVERLOAD_MISUSE"


class ComponentCode(str, Enum):
    SIDEWALL_SHEET = "SIDEWALL_SHEET"
    STIFFENER = "STIFFENER"
    ROOF_PANEL = "ROOF_PANEL"
    ANCHOR_BOLT = "ANCHOR_BOLT"
    BOLT_PACK = "BOLT_PACK"
    AERATION_FAN = "AERATION_FAN"
    UNLOAD_SYSTEM = "UNLOAD_SYSTEM"


# --------------------------------------------------------------------------
# Immutable reference / derived entities — ONLY id + created_at (PRD 2.5)
# --------------------------------------------------------------------------


class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    seal_required: bool
    min_design_wind_speed_mph: int
    seismic_design_category: str
    permit_review_days: int
    created_at: str


class GrainProfile(TypedDict):
    id: str
    grain_code: str
    bulk_density_kg_per_m3: int
    janssen_k_ratio: float
    max_safe_moisture_pct: float
    aeration_cfm_per_m3_base: float
    drying_multiplier: float
    created_at: str


class CoatingSpec(TypedDict):
    id: str
    coating_code: str
    zinc_mass_g_per_m2: int
    coating_cost_per_kg_cents: int
    changeover_minutes: int
    max_ambient_moisture_pct: float
    corrosion_class: str
    created_at: str


class RollFormingLine(TypedDict):
    id: str
    line_code: str
    max_gauge_mm: float
    created_at: str


class KitLine(TypedDict):
    id: str
    dealer_order_id: str
    component_code: str
    quantity: int
    unit_price_cents: int
    extended_cents: int
    weight_kg: float
    cube_m3: float
    created_at: str


# --------------------------------------------------------------------------
# Mutable entities — id + created_at + updated_at + version (PRD 2.5)
# --------------------------------------------------------------------------


class Engineer(TypedDict):
    id: str
    name: str
    license_number: str
    licensed_jurisdiction_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    name: str
    region_code: str
    jurisdiction_id: str
    credit_limit_cents: int
    credit_committed_cents: int
    credit_available_cents: int
    program_tier: str
    staging_slots: int
    staged_kit_count: int
    high_cube_access: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BinDesign(TypedDict):
    id: str
    dealer_id: str
    jurisdiction_id: str
    grain_profile_id: str
    coating_spec_id: str
    author_engineer_id: str
    sealed_by_engineer_id: Optional[str]
    diameter_m: float
    eave_height_m: float
    roof_pitch_deg: int
    design_wind_speed_mph: int
    moisture_pct: float
    design_method: str
    seal_required: bool
    circumference_m: float
    sheets_per_course: int
    sheet_courses: int
    sidewall_sheet_count: int
    roof_panel_count: int
    capacity_m3: float
    grain_lateral_kpa: float
    moisture_factor: float
    grain_demand_kpa: float
    wind_demand_kpa: float
    seismic_demand_kpa: float
    governing_demand_kpa: float
    governing_load_case: str
    required_stiffener_count: int
    utilization_ratio: float
    sheet_gauge_mm: float
    roof_ring_required: bool
    revision_round: int
    sealed_at: Optional[str]
    permit_ready_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignAnalysis(TypedDict):
    id: str
    bin_design_id: str
    analysis_index: int
    design_method: str
    allowable_kpa_m: float
    governing_load_case: str
    governing_demand_kpa: float
    required_stiffener_count: int
    utilization_ratio: float
    verdict: str
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class CoilLot(TypedDict):
    id: str
    coating_spec_id: str
    heat_number: str
    gauge_mm: float
    received_kg: float
    reserved_kg: float
    consumed_kg: float
    scrap_kg: float
    remaining_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RollFormingRun(TypedDict):
    id: str
    roll_forming_line_id: str
    coil_lot_id: str
    dealer_order_id: str
    coating_code: str
    window_start: str
    window_end: str
    planned_kg: float
    consumed_kg: float
    scrap_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DealerOrder(TypedDict):
    id: str
    dealer_id: str
    bin_design_id: str
    order_season: str
    aeration_package: str
    unload_system: str
    kit_subtotal_cents: int
    season_uplift_cents: int
    program_discount_cents: int
    net_subtotal_cents: int
    freight_surcharge_pct: float
    freight_surcharge_cents: int
    total_cents: int
    required_deposit_cents: int
    deposit_paid_cents: int
    credit_hold_cents: int
    kit_weight_kg: float
    kit_cube_m3: float
    grain_mass_kg: float
    required_fan_cfm: int
    drying_hours_estimate: int
    unload_rate_bph: int
    freight_load_id: Optional[str]
    allocated_freight_cents: int
    freight_sequence: Optional[int]
    installation_crew_id: Optional[str]
    production_status: str
    financial_status: str
    installation_readiness: str
    created_at: str
    updated_at: str
    version: int


class FreightLoad(TypedDict):
    id: str
    dealer_id: str
    trailer_type: str
    allocation_basis: str
    yard_window_start: str
    yard_window_end: str
    max_cube_m3: float
    max_weight_kg: int
    assigned_cube_m3: float
    assigned_weight_kg: float
    cube_utilization_pct: float
    linehaul_cost_cents: int
    order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationCrew(TypedDict):
    id: str
    dealer_id: str
    crew_name: str
    certification_tier: str
    max_diameter_m: float
    certified_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldFailure(TypedDict):
    id: str
    dealer_order_id: str
    bin_design_id: str
    failure_mode: str
    observed_load_kpa: float
    measured_coating_loss_pct: float
    service_years: float
    structural_verdict: Optional[str]
    corrosion_verdict: Optional[str]
    determined_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
