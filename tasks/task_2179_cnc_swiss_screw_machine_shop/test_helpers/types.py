"""Domain types: entity TypedDicts, status enums and the role enum."""

from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_PLANNER = "ShopPlanner"
    MACHINIST = "Machinist"
    INSPECTOR = "Inspector"
    QUALITY_MANAGER = "QualityManager"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertificationCode(str, Enum):
    SWISS_SETUP = "SWISS_SETUP"
    LIGHTS_OUT = "LIGHTS_OUT"
    CMM = "CMM"
    DEBURR = "DEBURR"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RUNNING = "RUNNING"
    DOWN = "DOWN"


class AlloyCode(str, Enum):
    SS303 = "303SS"
    SS316 = "316SS"
    C360 = "C360"
    AL6061 = "6061AL"
    L12L14 = "12L14"


class GaugeType(str, Enum):
    MICROMETER = "MICROMETER"
    BORE_GAUGE = "BORE_GAUGE"
    OPTICAL_COMPARATOR = "OPTICAL_COMPARATOR"
    CMM = "CMM"


class GaugeStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    CALIBRATION_DUE = "CALIBRATION_DUE"
    GRR_FAILED = "GRR_FAILED"
    RETIRED = "RETIRED"


class BarStockLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CERTIFIED = "CERTIFIED"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    ACCEPTED = "ACCEPTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class CostingBasis(str, Enum):
    STANDARD_CYCLE = "STANDARD_CYCLE"
    HISTORICAL_CYCLE = "HISTORICAL_CYCLE"


class BlanketPoStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class KanbanReleaseStatus(str, Enum):
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    SHORT_CLOSED = "SHORT_CLOSED"


class MachiningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    MACHINING_COMPLETE = "MACHINING_COMPLETE"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    IN_SPC = "IN_SPC"
    QUALITY_HOLD = "QUALITY_HOLD"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ToolAssignmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OFFSET_HOLD = "OFFSET_HOLD"
    LIFE_EXPIRED = "LIFE_EXPIRED"
    RETIRED = "RETIRED"


class SubgroupDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    MARGINAL = "MARGINAL"
    REJECT = "REJECT"


class RoutingStepStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class RoutingOperation(str, Enum):
    DEBURR = "DEBURR"
    WASH = "WASH"
    HEAT_TREAT = "HEAT_TREAT"
    PLATING = "PLATING"
    INSPECTION_100PCT = "INSPECTION_100PCT"


class DispositionDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    RELEASE_HOLD = "RELEASE_HOLD"


# --- Entities carrying id + created_at + updated_at + version ----------------


class Operator(TypedDict):
    id: str
    name: str
    badge_code: str
    certifications: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    asset_tag: str
    model: str
    max_bar_diameter_mm: float
    lights_out_certified: bool
    status: str
    current_work_order_id: Optional[str]
    chip_accrual_by_alloy: Dict[str, float]
    coolant_makeup_liters: float
    last_reclamation_credit_cents: Optional[int]
    lifetime_reclamation_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    part_number: str
    alloy_code: str
    bar_diameter_mm: float
    cut_off_length_mm: float
    cycle_time_sec: float
    setup_hours: float
    lights_out_eligible: bool
    secondary_required: bool
    secondary_minutes_per_piece: float
    material_cost_cents_per_meter: int
    finished_mass_g: float
    observed_avg_cycle_time_sec: Optional[float]
    observed_accepted_qty: int
    created_at: str
    updated_at: str
    version: int


class Characteristic(TypedDict):
    id: str
    part_id: str
    char_code: str
    nominal: float
    usl: float
    lsl: float
    cpk_min: float
    subgroup_size: int
    sample_freq_pieces: int
    required_gauge_type: str
    created_at: str
    updated_at: str
    version: int


class Gauge(TypedDict):
    id: str
    gauge_code: str
    gauge_type: str
    calibrated_at: str
    calibration_due_at: str
    grr_pct: float
    status: str
    calibration_count: int
    created_at: str
    updated_at: str
    version: int


class BarStockLot(TypedDict):
    id: str
    heat_number: str
    alloy_code: str
    bar_diameter_mm: float
    bar_length_mm: float
    bars_received: int
    mass_kg_per_meter: float
    feeder_slots: int
    total_length_mm: float
    available_length_mm: float
    reserved_length_mm: float
    consumed_length_mm: float
    status: str
    certificate_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    part_id: str
    customer_code: str
    lot_qty: int
    requested_lights_out_hours: float
    costing_basis: Optional[str]
    cycle_time_used_sec: Optional[float]
    effective_qty: Optional[int]
    run_cost_cents: Optional[int]
    setup_cost_cents: Optional[int]
    secondary_cost_cents: Optional[int]
    material_cost_cents: Optional[int]
    quoted_lot_cost_cents: Optional[int]
    quoted_unit_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlanketPO(TypedDict):
    id: str
    quote_id: str
    part_id: str
    customer_po_number: str
    total_committed_qty: int
    expires_on: str
    list_unit_price_cents: int
    pre_rebate_total_cents: int
    rebate_pct: float
    net_unit_price_cents: int
    committed_value_cents: int
    remaining_qty: int
    open_released_qty: int
    fulfilled_qty: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KanbanRelease(TypedDict):
    id: str
    blanket_po_id: str
    qty: int
    due_at: str
    fulfilled_qty: int
    close_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    release_id: str
    machine_id: str
    bar_lot_id: str
    part_id: str
    machinist_operator_id: Optional[str]
    qty_ordered: int
    scheduled_start_at: str
    scheduled_end_at: str
    lights_out_hours: float
    required_length_mm: float
    bars_reserved: int
    reserved_length_mm: float
    actual_run_seconds: Optional[float]
    qty_good: int
    qty_scrap: int
    chip_kg: float
    machining_status: str
    quality_status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ToolAssignment(TypedDict):
    id: str
    machine_id: str
    station: int
    tool_code: str
    expected_life_pieces: int
    drift_limit_um: float
    pieces_since_index: int
    cumulative_drift_um: float
    offset_log_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoutingStep(TypedDict):
    id: str
    work_order_id: str
    predecessor_step_id: Optional[str]
    sequence: int
    operation: str
    status: str
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Immutable observation: id + created_at only, no updated_at, no version ---


class SpcSample(TypedDict):
    id: str
    work_order_id: str
    characteristic_id: str
    gauge_id: str
    inspector_operator_id: str
    piece_index: int
    measurements: List[float]
    mean: float
    range: float
    sigma_within: float
    cpk_short_term: float
    out_of_spec_count: int
    disposition: str
    created_at: str


class QualitySummary(TypedDict):
    work_order_id: str
    characteristic_count: int
    sample_count: int
    required_sample_count: int
    out_of_spec_count: int
    cpk_short_term_min: Optional[float]
    ppk_long_term_min: Optional[float]
