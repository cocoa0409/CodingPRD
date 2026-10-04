"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3).

Entities carrying the common field set have id + created_at + updated_at +
version. EmissionsReading and OutletSale are the PRD §2.5 exceptions: they
carry ONLY id and created_at — no updated_at, no version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FOUNDRY_MANAGER = "FoundryManager"
    MELT_OPERATOR = "MeltOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    SEASONING_LEAD = "SeasoningLead"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    RETAIL_PLANNER = "RetailPlanner"
    OUTLET_MANAGER = "OutletManager"


ALL_ROLES = [r.value for r in UserRole]


class ProductCategory(str, Enum):
    SKILLET = "SKILLET"
    DUTCH_OVEN = "DUTCH_OVEN"
    GRIDDLE = "GRIDDLE"
    GRILL_PAN = "GRILL_PAN"
    BAKEWARE = "BAKEWARE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductionOrderState(str, Enum):
    PLANNED = "PLANNED"
    MOLDING = "MOLDING"
    POURING = "POURING"
    FINISHING = "FINISHING"
    SEASONING = "SEASONING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ProductionOrderPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ScrapTier(str, Enum):
    GREEN = "GREEN"
    WATCH = "WATCH"
    RED = "RED"


class FurnaceId(str, Enum):
    FURNACE_A = "FURNACE_A"
    FURNACE_B = "FURNACE_B"


class MeltBatchState(str, Enum):
    CHARGING = "CHARGING"
    MELTING = "MELTING"
    CHEMISTRY_CHECK = "CHEMISTRY_CHECK"
    ADJUSTMENT = "ADJUSTMENT"
    CERTIFIED = "CERTIFIED"
    TAPPED = "TAPPED"
    EXHAUSTED = "EXHAUSTED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class MoldState(str, Enum):
    PREPARED = "PREPARED"
    POURED = "POURED"
    SHAKEOUT_DONE = "SHAKEOUT_DONE"
    SAND_RECLAIMED = "SAND_RECLAIMED"
    CANCELLED = "CANCELLED"


class CastingUnitState(str, Enum):
    POURED = "POURED"
    SHAKEOUT_DONE = "SHAKEOUT_DONE"
    DEFECT_REVIEW = "DEFECT_REVIEW"
    REWORK = "REWORK"
    FINISHED = "FINISHED"
    SEASONING_QUEUED = "SEASONING_QUEUED"
    SEASONED = "SEASONED"
    SCRAPPED = "SCRAPPED"


class ScrapReason(str, Enum):
    DEFECT = "DEFECT"
    ORDER_CANCEL = "ORDER_CANCEL"


class DefectType(str, Enum):
    POROSITY = "POROSITY"
    COLD_SHUT = "COLD_SHUT"
    MISRUN = "MISRUN"
    SAND_INCLUSION = "SAND_INCLUSION"
    DIMENSIONAL = "DIMENSIONAL"
    CRACK = "CRACK"


class DefectSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DefectReportStatus(str, Enum):
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"


class Disposition(str, Enum):
    REWORK = "REWORK"
    SCRAP = "SCRAP"
    USE_AS_IS = "USE_AS_IS"


class InspectOutcome(str, Enum):
    PASS = "PASS"
    DEFECT = "DEFECT"


class OilType(str, Enum):
    SOYBEAN = "SOYBEAN"
    CANOLA = "CANOLA"
    FLAXSEED = "FLAXSEED"


class SeasoningBatchState(str, Enum):
    COATING = "COATING"
    BAKING = "BAKING"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class ReleaseDecision(str, Enum):
    RELEASE = "RELEASE"
    FAIL = "FAIL"


class CertifyDecision(str, Enum):
    CERTIFY = "CERTIFY"
    ORDER_ADJUSTMENT = "ORDER_ADJUSTMENT"


class PermitType(str, Enum):
    AIR_EMISSIONS = "AIR_EMISSIONS"
    SAND_RECLAMATION = "SAND_RECLAMATION"
    DUST_CONTROL = "DUST_CONTROL"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    BREACH = "BREACH"
    REMEDIATION = "REMEDIATION"


class CompliancePeriod(str, Enum):
    MONTHLY = "MONTHLY"


class EmissionSource(str, Enum):
    MELT_FURNACE = "MELT_FURNACE"
    SHAKEOUT_LINE = "SHAKEOUT_LINE"
    SAND_PLANT = "SAND_PLANT"
    SEASONING_OVEN = "SEASONING_OVEN"


class AllocationChannel(str, Enum):
    RETAIL_CHAIN = "RETAIL_CHAIN"
    ECOMMERCE = "ECOMMERCE"
    FACTORY_OUTLET = "FACTORY_OUTLET"
    MUSEUM_STORE = "MUSEUM_STORE"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OutletChannel(str, Enum):
    FACTORY_OUTLET = "FACTORY_OUTLET"
    MUSEUM_STORE = "MUSEUM_STORE"


# --- Entity TypedDicts ---------------------------------------------------------
# Common-fields entities: id, created_at, updated_at, version (PRD §2.5).

class Product(TypedDict, total=False):
    id: str
    sku_code: str
    name: str
    category: str
    target_weight_oz: float
    weight_tolerance_oz: float
    target_diameter_in: float
    diameter_tolerance_in: float
    min_wall_thickness_in: float
    wholesale_price_cents: int
    msrp_cents: int
    import_landed_cost_cents: int
    peak_season_start_week: int
    peak_season_end_week: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    product_id: str
    planned_quantity: int
    scheduled_week: int
    state: str
    posture: str
    scrap_tier: str
    poured_units: int
    good_units: int
    scrapped_units: int
    defect_scrapped_units: int
    scrap_weighted_units: float
    scrap_index: float
    labor_hours_actual: Optional[float]
    energy_kwh_actual: Optional[float]
    unit_cost_provisional_cents: int
    unit_cost_final_cents: Optional[int]
    margin_flag: bool
    created_at: str
    updated_at: str
    version: int


class MeltBatch(TypedDict, total=False):
    id: str
    production_order_id: str
    furnace_id: str
    planned_tap_start: str
    planned_tap_end: str
    planned_iron_lbs: float
    planned_pig_iron_pct: float
    planned_scrap_steel_pct: float
    planned_returns_pct: float
    planned_alloy_pct: float
    state: str
    state_before_hold: Optional[str]
    adjustment_count: int
    pig_iron_lbs: float
    scrap_steel_lbs: float
    returns_lbs: float
    alloy_lbs: float
    planned_charge_cost_cents: int
    actual_charge_cost_cents: int
    carbon_pct: Optional[float]
    silicon_pct: Optional[float]
    manganese_pct: Optional[float]
    sulfur_pct: Optional[float]
    phosphorus_pct: Optional[float]
    bath_temp_f: Optional[float]
    carbon_equivalent: Optional[float]
    chemistry_recorded_by: Optional[str]
    certified_by: Optional[str]
    tapped_temp_f: Optional[float]
    tapped_lbs: Optional[float]
    slag_loss_lbs: Optional[float]
    poured_lbs: float
    remaining_iron_lbs: Optional[float]
    returns_credit_lbs: float
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict, total=False):
    id: str
    production_order_id: str
    new_sand_pct: float
    reclaimed_sand_pct: float
    moisture_pct: float
    clay_pct: float
    sand_weight_lbs: float
    state: str
    reclaimed_sand_lbs: Optional[float]
    dust_collected_lbs: Optional[float]
    reclaim_loss_lbs: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CastingUnit(TypedDict, total=False):
    id: str
    production_order_id: str
    melt_batch_id: str
    mold_id: str
    seasoning_batch_id: Optional[str]
    pour_weight_oz: float
    measured_weight_oz: Optional[float]
    measured_diameter_in: Optional[float]
    measured_wall_thickness_in: Optional[float]
    state: str
    rework_count: int
    scrap_reason: Optional[str]
    scrapped_after_rework: bool
    created_at: str
    updated_at: str
    version: int


class DefectReport(TypedDict, total=False):
    id: str
    casting_unit_id: str
    defect_type: str
    severity: str
    status: str
    disposition: Optional[str]
    dispositioned_by: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasoningBatch(TypedDict, total=False):
    id: str
    production_order_id: str
    oil_type: str
    coating_count: int
    unit_ids: List[str]
    unit_count: int
    planned_bake_start: str
    planned_bake_end: str
    oven_id: str
    state: str
    actual_bake_temp_f: Optional[float]
    oil_lot_number: Optional[str]
    coa_reference: Optional[str]
    bake_recorded_by: Optional[str]
    bake_duration_min: Optional[int]
    cure_score: Optional[int]
    food_safety_verified: Optional[bool]
    released_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvironmentalPermit(TypedDict, total=False):
    id: str
    permit_type: str
    limit_value: float
    measurement_unit: str
    compliance_period: str
    status: str
    over_limit_reading_count_current_period: int
    current_sand_rate: Optional[float]
    last_breach_reading_recorded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmissionsReading(TypedDict, total=False):
    # Append-only event (PRD §2.5): ONLY id + created_at plus own fields.
    id: str
    permit_id: str
    reading_value: float
    source: str
    recorded_by: str
    created_at: str


class InventoryRecord(TypedDict, total=False):
    id: str
    product_id: str
    on_hand_units: int
    reserved_units: int
    shipped_units: int
    outlet_sold_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class RetailAllocation(TypedDict, total=False):
    id: str
    inventory_record_id: str
    channel: str
    allocated_qty: int
    ship_week: str
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutletSale(TypedDict, total=False):
    # Append-only event (PRD §2.5): ONLY id + created_at plus own fields.
    id: str
    product_id: str
    channel: str
    qty: int
    unit_price_cents: int
    floor_price_cents: int
    recorded_by: str
    created_at: str
