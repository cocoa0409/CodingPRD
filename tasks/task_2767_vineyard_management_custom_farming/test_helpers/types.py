"""Domain types for the Vineyard Management & Custom Farming API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    VINEYARD_MANAGER = "VineyardManager"
    AGRONOMIST = "Agronomist"
    APPLICATOR = "Applicator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTROLLER = "Controller"
    CREW_SUPERVISOR = "CrewSupervisor"
    CLIENT_OWNER = "ClientOwner"


# ─── Enumerations carried on stored resources ─────────

class FarmingStatus(str, Enum):
    ESTABLISHING = "ESTABLISHING"
    BEARING = "BEARING"
    REMOVED = "REMOVED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    REENTRY_RESTRICTED = "REENTRY_RESTRICTED"
    PHI_RESTRICTED = "PHI_RESTRICTED"


class HarvestPosture(str, Enum):
    NOT_ESTIMATED = "NOT_ESTIMATED"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"


class Variety(str, Enum):
    CABERNET_SAUVIGNON = "CABERNET_SAUVIGNON"
    CHARDONNAY = "CHARDONNAY"
    PINOT_NOIR = "PINOT_NOIR"
    ZINFANDEL = "ZINFANDEL"
    SYRAH = "SYRAH"


class Rootstock(str, Enum):
    ROOTSTOCK_1103P = "ROOTSTOCK_1103P"
    ROOTSTOCK_110R = "ROOTSTOCK_110R"
    ROOTSTOCK_SO4 = "ROOTSTOCK_SO4"
    RIPARIA_GLOIRE = "RIPARIA_GLOIRE"
    ST_GEORGE = "ST_GEORGE"


class TrellisSystem(str, Enum):
    VSP = "VSP"
    SPRAWL = "SPRAWL"
    QUADRILATERAL_CORDON = "QUADRILATERAL_CORDON"
    HEAD_TRAINED = "HEAD_TRAINED"
    GDC = "GDC"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class QualityTarget(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    BULK = "BULK"


class BudgetPosture(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    AT_RISK = "AT_RISK"
    EXHAUSTED = "EXHAUSTED"


class PayStructure(str, Enum):
    PIECE_RATE = "PIECE_RATE"
    HOURLY = "HOURLY"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TaskType(str, Enum):
    PRUNING = "PRUNING"
    SUCKERING = "SUCKERING"
    LEAFING = "LEAFING"
    HARVEST = "HARVEST"


class ExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PayrollStatus(str, Enum):
    NOT_PAYABLE = "NOT_PAYABLE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"


class CancelReason(str, Enum):
    WEATHER = "WEATHER"
    CLIENT_REQUEST = "CLIENT_REQUEST"
    CREW_UNAVAILABLE = "CREW_UNAVAILABLE"
    REENTRY_RESTRICTION = "REENTRY_RESTRICTION"


class PayrollAction(str, Enum):
    APPROVE = "APPROVE"
    PAY = "PAY"


class IrrigationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"


class PestCode(str, Enum):
    POWDERY_MILDEW = "POWDERY_MILDEW"
    VINE_MEALYBUG = "VINE_MEALYBUG"
    BOTRYTIS = "BOTRYTIS"
    LEAFHOPPER = "LEAFHOPPER"


class SprayStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"


class YieldMethod(str, Enum):
    CLUSTER_COUNT = "CLUSTER_COUNT"
    BERRY_SAMPLE = "BERRY_SAMPLE"


class WindowPosture(str, Enum):
    OPEN = "OPEN"
    NEARLY_FULL = "NEARLY_FULL"
    FULL = "FULL"


class LoadStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    MOG_EXCESS = "MOG_EXCESS"
    LOW_BRIX = "LOW_BRIX"
    ROT_DAMAGE = "ROT_DAMAGE"
    LATE_ARRIVAL = "LATE_ARRIVAL"


class SettlementMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ─── Mutable resources (PRD §2.4: id, created_at, updated_at, version) ───

class Vineyard(TypedDict):
    id: str
    name: str
    owner_legal_name: str
    ava_region: str
    client_contact_email: str
    block_count: int
    managed_acres: float
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict):
    id: str
    vineyard_id: str
    block_code: str
    variety: str
    clone: str
    rootstock: str
    trellis_system: str
    planting_year: int
    vine_spacing_ft: float
    row_spacing_ft: float
    acres: float
    vines_per_acre: int
    vine_count: int
    farming_status: str
    compliance_posture: str
    harvest_posture: str
    replaces_block_id: Optional[str]
    contract_id: Optional[str]
    contracted_acres: Optional[float]
    per_acre_fee_override: Optional[float]
    rei_clear_at: Optional[str]
    phi_clear_at: Optional[str]
    season_applied_inches: float
    governing_estimate_tons: float
    committed_harvest_tons: float
    received_tons: float
    remaining_estimated_tons: float
    created_at: str
    updated_at: str
    version: int


class CustomFarmingContract(TypedDict):
    id: str
    vineyard_id: str
    contract_status: str
    per_acre_annual_fee: float
    cost_pass_through_pct: float
    quality_incentive_per_ton: float
    quality_brix_threshold: float
    period_overhead_pool: float
    period_start: str
    period_end: str
    client_signature_name: Optional[str]
    enrolled_block_count: int
    total_contracted_acres: float
    accrued_quality_incentive: float
    projected_total_billable: float
    settled_period_count: int
    last_settlement_total: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FarmingPlan(TypedDict):
    id: str
    block_id: str
    plan_year: int
    plan_status: str
    quality_target: str
    pruning_budget_per_acre: float
    canopy_budget_per_acre: float
    irrigation_budget_per_acre: float
    pest_budget_per_acre: float
    seasonal_water_cap_inches: float
    total_budget: float
    committed_cost: float
    remaining_budget: float
    budget_posture: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborCrew(TypedDict):
    id: str
    crew_name: str
    pay_structure: str
    crew_size: int
    base_hourly_rate: float
    piece_rate_per_vine: float
    vines_per_hour_standard: float
    task_capabilities: List[str]
    pest_certified: bool
    crew_status: str
    scheduled_work_order_count: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    block_id: str
    farming_plan_id: str
    crew_id: str
    task_type: str
    scheduled_start: str
    scheduled_end: str
    planned_vines: int
    planned_hours: float
    estimated_labor_cost: float
    actual_vines: Optional[int]
    actual_hours: Optional[float]
    actual_labor_cost: Optional[float]
    execution_status: str
    payroll_status: str
    cancel_reason: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IrrigationEvent(TypedDict):
    id: str
    block_id: str
    farming_plan_id: str
    scheduled_start: str
    scheduled_end: str
    et0_inches: float
    crop_coefficient: float
    soil_moisture_pct: float
    field_capacity_pct: float
    root_zone_depth_in: float
    effective_rain_inches: float
    water_unit_cost_per_acre_inch: float
    deficit_factor: float
    et_demand_inches: float
    target_inches: float
    soil_shortfall_inches: float
    refill_inches: float
    gross_requirement_inches: float
    seasonal_allowance_inches: float
    recommended_inches: float
    applied_inches: Optional[float]
    water_cost: Optional[float]
    applied_at: Optional[str]
    irrigation_status: str
    created_at: str
    updated_at: str
    version: int


class SprayRecord(TypedDict):
    id: str
    block_id: str
    farming_plan_id: str
    pest_observation_id: str
    product_name: str
    active_ingredient: str
    rei_hours: int
    phi_days: int
    rate_per_acre: float
    material_cost: float
    spray_status: str
    recommended_by_user_id: str
    applied_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    applicator_license_no: Optional[str]
    wind_speed_mph: Optional[float]
    applied_at: Optional[str]
    rei_clear_at: Optional[str]
    phi_clear_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WineryDeliveryWindow(TypedDict):
    id: str
    winery_name: str
    window_start: str
    window_end: str
    capacity_tons: float
    committed_tons: float
    remaining_tons: float
    window_posture: str
    created_at: str
    updated_at: str
    version: int


class HarvestLoad(TypedDict):
    id: str
    block_id: str
    crew_id: str
    delivery_window_id: str
    estimated_tons: float
    delivery_eta: str
    load_status: str
    gross_tons_at_dispatch: Optional[float]
    gross_tons: Optional[float]
    tare_tons: Optional[float]
    mog_deduct_pct: Optional[float]
    brix_at_receipt: Optional[float]
    net_tons: Optional[float]
    quality_incentive_amount: Optional[float]
    rejection_reason: Optional[str]
    dispatched_at: Optional[str]
    received_at: Optional[str]
    rejected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Immutable event records (PRD §2.4: id and created_at only) ───
# "a filed PestObservation and a filed YieldEstimate each carry only id and
# created_at. Neither has an updated_at field and neither has a version field."

class PestObservation(TypedDict):
    id: str
    block_id: str
    pest_code: str
    incidence_pct: float
    severity_index: int
    scouting_note: Optional[str]
    observed_at: str
    scout_user_id: str
    action_threshold_pct: float
    exceeds_threshold: bool
    created_at: str


class YieldEstimate(TypedDict):
    id: str
    block_id: str
    method: str
    sample_date: str
    avg_clusters_per_vine: float
    avg_cluster_weight_lb: Optional[float]
    berries_per_cluster: Optional[float]
    avg_berry_weight_g: Optional[float]
    days_to_harvest: Optional[int]
    vine_count_at_estimate: int
    estimated_tons: float
    estimated_tons_per_acre: float
    created_at: str


# ─── Settlement statement (PRD §3.9 — a computed read, not a stored row) ───

class SettlementStatement(TypedDict):
    contract_id: str
    settlement_mode: str
    period_end_date: str
    direct_cost_total: float
    management_fee_base: float
    pass_through: float
    tier_basis: float
    volume_discount_pct: float
    volume_discount: float
    quality_incentive: float
    total_billable: float
    contract_status: str
