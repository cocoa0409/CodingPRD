"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ENERGY_MANAGER = "EnergyManager"
    TRADING_ANALYST = "TradingAnalyst"
    SMELTER_MANAGER = "SmelterManager"
    CONTROLLER = "Controller"
    VP_OPERATIONS = "VPOperations"
    EHS_MANAGER = "EHSManager"


class RegionCode(str, Enum):
    NA_NORTHWEST = "NA_NORTHWEST"
    NA_MIDWEST = "NA_MIDWEST"
    EU_NORDIC = "EU_NORDIC"
    AU_EAST = "AU_EAST"
    GLOBAL = "GLOBAL"


class OperatingPosture(str, Enum):
    FULL_OPERATION = "FULL_OPERATION"
    PARTIAL_CURTAILMENT = "PARTIAL_CURTAILMENT"
    FULL_CURTAILMENT = "FULL_CURTAILMENT"
    SHUTDOWN = "SHUTDOWN"


class PotlineStatus(str, Enum):
    OPERATING = "OPERATING"
    CURTAILED = "CURTAILED"
    IDLE = "IDLE"
    RESTARTING = "RESTARTING"
    SHUTDOWN = "SHUTDOWN"


class RestartCostClass(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ComponentType(str, Enum):
    FIXED = "FIXED"
    MARKET_INDEXED = "MARKET_INDEXED"
    INTERRUPTIBLE = "INTERRUPTIBLE"


class Instrument(str, Enum):
    POWER_SPOT = "POWER_SPOT"
    ALUMINUM_LME = "ALUMINUM_LME"
    REGIONAL_PREMIUM = "REGIONAL_PREMIUM"
    ALUMINA_INDEX = "ALUMINA_INDEX"


class HedgeInstrument(str, Enum):
    LME_SWAP = "LME_SWAP"
    PREMIUM_SWAP = "PREMIUM_SWAP"


class HedgeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class PricingModel(str, Enum):
    COST_PLUS = "COST_PLUS"
    MARKET_LINKED = "MARKET_LINKED"


class TriggerType(str, Enum):
    POWER_PRICE = "POWER_PRICE"
    METAL_PRICE = "METAL_PRICE"
    GRID_EMERGENCY = "GRID_EMERGENCY"
    MAINTENANCE = "MAINTENANCE"


class DecisionStatus(str, Enum):
    ECONOMIC_REVIEW = "ECONOMIC_REVIEW"
    LABOR_REVIEW = "LABOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class RestartPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class PermitType(str, Enum):
    EMISSIONS = "EMISSIONS"
    SPL_DISPOSAL = "SPL_DISPOSAL"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class LaborAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ProductForm(str, Enum):
    BILLET = "BILLET"
    SLAB = "SLAB"
    VALUE_ADDED = "VALUE_ADDED"


class ProductionPlanStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class Smelter(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    rated_capacity_tpd: float
    labor_headcount: int
    operating_posture: str
    open_hedged_tonnes: float
    curtailed_capacity_tpd: float
    hedge_coverage_ratio: float
    created_at: str
    updated_at: str
    version: int


class Potline(TypedDict, total=False):
    id: str
    smelter_id: str
    line_code: str
    capacity_tpd: float
    amperage_ka: float
    operating_status: str
    curtailment_depth_pct: float
    curtailed_since: Optional[str]
    last_full_shutdown_at: Optional[str]
    active_decision_id: Optional[str]
    restart_cost_class: str
    created_at: str
    updated_at: str
    version: int


class PowerContract(TypedDict, total=False):
    id: str
    smelter_id: str
    supplier_name: str
    window_start: str
    window_end: str
    components: List[dict]
    take_or_pay_pct: float
    status: str
    interruptible_hours_used: float
    forward_cost_per_mwh: Optional[float]
    settled_cost_per_mwh: Optional[float]
    month_to_date_settlement_usd: Optional[float]
    take_or_pay_exposed: bool
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict, total=False):
    id: str
    smelter_id: str
    instrument: str
    volume_tonnes: float
    strike_price_usd: float
    delivery_month: str
    status: str
    closed_price_usd: Optional[float]
    realized_pnl_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AluminaSupplyAgreement(TypedDict, total=False):
    id: str
    smelter_id: str
    refinery_name: str
    pricing_model: str
    base_cost_per_tonne: Optional[float]
    markup_pct: Optional[float]
    market_discount_pct: Optional[float]
    monthly_volume_tonnes: float
    current_transfer_price: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CurtailmentDecision(TypedDict, total=False):
    id: str
    potline_id: str
    trigger_type: str
    depth_pct: float
    planned_start: str
    planned_end: str
    status: str
    economics_snapshot: dict
    proposed_by_user_id: str
    economic_reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestartPlan(TypedDict, total=False):
    id: str
    potline_id: str
    planned_restart_at: str
    status: str
    restart_cost_class: str
    estimated_cost_usd: float
    actual_cost_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EnvironmentalPermit(TypedDict, total=False):
    id: str
    smelter_id: str
    permit_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborAgreement(TypedDict, total=False):
    id: str
    smelter_id: str
    union_name: str
    notice_period_days: int
    severance_weeks_per_year: float
    community_impact_clause: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionPlan(TypedDict, total=False):
    id: str
    smelter_id: str
    period_month: str
    allocations: List[dict]
    status: str
    total_tonnes: float
    total_margin_usd: float
    created_at: str
    updated_at: str
    version: int


# Append-only records carry ONLY id + created_at (PRD §2.5).

class PriceObservation(TypedDict, total=False):
    id: str
    instrument: str
    region_code: str
    observed_at: str
    price_usd: float
    created_at: str


class InterruptEvent(TypedDict, total=False):
    id: str
    contract_id: str
    start_at: str
    end_at: str
    mw_reduced: float
    hours: float
    created_at: str
