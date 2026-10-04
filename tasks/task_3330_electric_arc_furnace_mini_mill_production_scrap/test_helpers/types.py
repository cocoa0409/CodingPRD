"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class MillDivision(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    AUTOMOTIVE = "AUTOMOTIVE"
    ENERGY = "ENERGY"


class MillPosture(str, Enum):
    NORMAL = "NORMAL"
    INTERRUPTED = "INTERRUPTED"


class GradeCategory(str, Enum):
    SHREDDED = "SHREDDED"
    BUSHLING = "BUSHLING"
    HMS = "HMS"
    DRI = "DRI"
    PIG_IRON = "PIG_IRON"


class IndexStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ContractType(str, Enum):
    FIXED = "FIXED"
    INDEXED = "INDEXED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"


class ProductForm(str, Enum):
    BILLET = "BILLET"
    BLOOM = "BLOOM"
    SLAB = "SLAB"


class GradeGroup(str, Enum):
    GROUP_A = "GROUP_A"
    GROUP_B = "GROUP_B"


class CertificationClass(str, Enum):
    STANDARD = "STANDARD"
    CERTIFIED = "CERTIFIED"


class HeatStatus(str, Enum):
    PLANNED = "PLANNED"
    CHARGED = "CHARGED"
    MELTDOWN_LOCKED = "MELTDOWN_LOCKED"
    TAPPED = "TAPPED"
    CAST = "CAST"
    ABORTED = "ABORTED"


class SheetStatus(str, Enum):
    RECORDED = "RECORDED"
    REVISED = "REVISED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class CampaignStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProductFamily(str, Enum):
    REBAR = "REBAR"
    BEAM = "BEAM"
    PLATE = "PLATE"
    WIRE_ROD = "WIRE_ROD"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class AllocationPriority(str, Enum):
    STANDARD = "STANDARD"
    STRATEGIC = "STRATEGIC"


class PricingMode(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class PriceBasis(str, Enum):
    CONTRACT_MONTH_INDEX = "CONTRACT_MONTH_INDEX"
    CURRENT_MONTH_INDEX = "CURRENT_MONTH_INDEX"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HONORED = "HONORED"
    LAPSED = "LAPSED"


class EventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class WaiverScope(str, Enum):
    HEAT = "HEAT"
    EVENT = "EVENT"


class ScorecardStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISTRIBUTED = "DISTRIBUTED"


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    MILL_OPERATOR = "MillOperator"
    SCHEDULER = "Scheduler"
    METALLURGIST = "Metallurgist"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    ACCOUNT_MANAGER = "AccountManager"
    QUALITY_ENGINEER = "QualityEngineer"
    ENERGY_DISPATCHER = "EnergyDispatcher"


# --- common-fields entities (id + created_at + updated_at + version) ---

class Mill(TypedDict, total=False):
    id: str
    name: str
    division: str
    furnace_capacity_tons: float
    caster_rate_tph: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class ProcurementContract(TypedDict, total=False):
    id: str
    mill_id: str
    supplier_name: str
    grade_category: str
    contract_type: str
    contract_price_cents: int
    committed_tons: float
    received_tons: float
    settlement_tons: float
    settlement_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Heat(TypedDict, total=False):
    id: str
    mill_id: str
    heat_number: str
    grade_id: str
    target_tap_weight_tons: float
    planned_tap_at: str
    energy_kwh: float
    charge_cost_cents: int
    scrap_surcharge_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MeltdownSheet(TypedDict, total=False):
    id: str
    heat_id: str
    revision_no: int
    cu_pct: float
    mn_pct: float
    chem_ok: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    mill_id: str
    name: str
    product_family: str
    grade_group: str
    planned_start: str
    planned_end: str
    roll_changes_used: int
    roll_change_budget: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    mill_id: str
    name: str
    market: str
    pricing_mode: str
    credit_status: str
    allocation_priority: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    mill_id: str
    product_family: str
    grade_id: str
    tons: float
    fulfillment_month: str
    base_price_cents_per_ton: int
    allocated_tons: float
    computed_price_cents: int
    price_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InterruptibleWindow(TypedDict, total=False):
    id: str
    mill_id: str
    label: str
    start_at: str
    end_at: str
    curtailment_credit_cents: int
    linked_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnergyEvent(TypedDict, total=False):
    id: str
    mill_id: str
    grid_operator: str
    called_at: str
    released_at: str
    waiver_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DivisionScorecard(TypedDict, total=False):
    id: str
    mill_id: str
    period: str
    revenue_cents: int
    material_cost_cents: int
    energy_cost_cents: int
    curtailment_credits_cents: int
    profit_cents: int
    profit_pool_cents: int
    headcount: int
    distribution_per_employee_cents: int
    remainder_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- lean entities (id + created_at only; no updated_at, no version) ---

class SurchargeIndex(TypedDict, total=False):
    id: str
    mill_id: str
    grade_category: str
    effective_month: str
    price_per_ton_cents: int
    status: str
    created_at: str


class ScrapLot(TypedDict, total=False):
    id: str
    contract_id: str
    mill_id: str
    received_on: str
    tons_received: float
    moisture_pct: float
    dry_tons: float
    cu_pct: float
    mn_pct: float
    remaining_tons: float
    status: str
    created_at: str


class Grade(TypedDict, total=False):
    id: str
    mill_id: str
    grade_code: str
    product_form: str
    grade_group: str
    certification_class: str
    cu_max_pct: float
    mn_min_pct: float
    mn_max_pct: float
    requires_energy_certified: bool
    created_at: str


class HeatChargeLine(TypedDict, total=False):
    id: str
    heat_id: str
    scrap_lot_id: str
    tons: float
    line_cost_cents: int
    created_at: str


class CampaignLine(TypedDict, total=False):
    id: str
    campaign_id: str
    heat_id: str
    campaign_grade_group: str
    created_at: str


class MillTestReport(TypedDict, total=False):
    id: str
    heat_id: str
    order_id: str
    report_no: str
    chemistry_snapshot: dict
    energy_certified: bool
    created_at: str


class PowerInterruptionWaiver(TypedDict, total=False):
    id: str
    mill_id: str
    scope: str
    scope_id: str
    granted_by: str
    reason: str
    created_at: str


class EnergyInterval(TypedDict, total=False):
    id: str
    heat_id: str
    interval_start: str
    interval_end: str
    kwh: float
    posture_at_interval: str
    created_at: str
