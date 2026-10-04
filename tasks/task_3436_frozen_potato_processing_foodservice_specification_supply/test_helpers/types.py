"""Domain types: entity TypedDicts, status enums, role enum.

Field names match the PRD exactly. Entities with the standard system-managed
property set (PRD §2.4) carry id/created_at/updated_at/version; the
ByproductBatch is the documented exception and carries only id/created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    GROWER_RELATIONS_MANAGER = "GrowerRelationsManager"
    GROWER = "Grower"
    STORAGE_OPERATOR = "StorageOperator"
    QUALITY_ASSURANCE_LEAD = "QualityAssuranceLead"
    PRODUCTION_PLANNER = "ProductionPlanner"
    ACCOUNT_MANAGER = "AccountManager"
    CHAIN_CUSTOMER = "ChainCustomer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class Region(str, Enum):
    COLUMBIA_BASIN = "COLUMBIA_BASIN"
    SNAKE_RIVER_VALLEY = "SNAKE_RIVER_VALLEY"
    RED_RIVER_VALLEY = "RED_RIVER_VALLEY"
    MAINE_AROOSTOOK = "MAINE_AROOSTOOK"


class Variety(str, Enum):
    RUSSET_BURBANK = "RUSSET_BURBANK"
    RANGER_RUSSET = "RANGER_RUSSET"
    UMATILLA_RUSSET = "UMATILLA_RUSSET"
    CLEARWATER_RUSSET = "CLEARWATER_RUSSET"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    FULFILLED = "FULFILLED"
    SHORTFALL_DECLARED = "SHORTFALL_DECLARED"


class LotStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    ALLOCATED = "ALLOCATED"
    CONSUMED = "CONSUMED"
    DISPOSED = "DISPOSED"


class LotOrigin(str, Enum):
    CONTRACTED = "CONTRACTED"
    IMPORT = "IMPORT"


class LotGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class Disposition(str, Enum):
    CONDEMNED_WASTE = "CONDEMNED_WASTE"
    CATTLE_FEED = "CATTLE_FEED"
    STARCH_RECOVERY = "STARCH_RECOVERY"


class FacilityPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    QUARANTINED = "QUARANTINED"


class CutFamily(str, Enum):
    STRAIGHT = "STRAIGHT"
    CRINKLE = "CRINKLE"
    WEDGE = "WEDGE"
    SHOESTRING = "SHOESTRING"


class CoatingType(str, Enum):
    NONE = "NONE"
    CLEAR = "CLEAR"
    SEASONED = "SEASONED"
    BATTER = "BATTER"


class SpecStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class PriorityTier(str, Enum):
    TIER_1_STRATEGIC = "TIER_1_STRATEGIC"
    TIER_2_PREFERRED = "TIER_2_PREFERRED"
    TIER_3_STANDARD = "TIER_3_STANDARD"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    ON_HOLD = "ON_HOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CUTTING = "CUTTING"
    BLANCHING = "BLANCHING"
    COATING = "COATING"
    FREEZING = "FREEZING"
    QA_HOLD = "QA_HOLD"
    REWORK = "REWORK"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED_ON_ARRIVAL = "REJECTED_ON_ARRIVAL"


class RouteType(str, Enum):
    DIRECT_CHAIN = "DIRECT_CHAIN"
    DISTRIBUTOR = "DISTRIBUTOR"


class ShortageStatus(str, Enum):
    OPEN = "OPEN"
    EXECUTED = "EXECUTED"


class ResponseMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    PRIORITY_WATERFALL = "PRIORITY_WATERFALL"


class BatchStream(str, Enum):
    WHOLE_LOT = "WHOLE_LOT"
    REJECTED_PRODUCT = "REJECTED_PRODUCT"


class Grower(TypedDict, total=False):
    id: str
    grower_code: str
    legal_name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class CropContract(TypedDict, total=False):
    id: str
    grower_id: str
    variety: str
    contracted_acres: float
    expected_yield_cwt_per_acre: float
    contracted_volume_cwt: float
    base_price_per_cwt_cents: int
    delivery_window_start: str
    delivery_window_end: str
    pending_amendment: Optional[Dict[str, Any]]
    delivered_volume_cwt: float
    settlement_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PotatoLot(TypedDict, total=False):
    id: str
    contract_id: Optional[str]
    shortage_event_id: Optional[str]
    facility_id: str
    origin: str
    variety: str
    gross_weight_cwt: float
    tare_weight_cwt: float
    net_weight_cwt: float
    defect_pct: float
    specific_gravity: float
    sugar_end_rating: float
    grade: str
    provisional_payment_cents: Optional[int]
    final_payment_cents: Optional[int]
    status: str
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageFacility(TypedDict, total=False):
    id: str
    facility_code: str
    capacity_cwt: int
    target_temp_f: float
    target_co2_pct: float
    current_stock_cwt: float
    posture: str
    recent_readings: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ProcessingLine(TypedDict, total=False):
    id: str
    line_code: str
    supported_cut_families: List[str]
    rated_throughput_cases_per_hour: int
    created_at: str
    updated_at: str
    version: int


class CutSpecification(TypedDict, total=False):
    id: str
    customer_id: str
    spec_code: str
    cut_family: str
    cut_size_mm: float
    coating_type: str
    target_color_units: float
    max_cook_time_sec: int
    sensory_panel_required: bool
    panel_score: Optional[float]
    ever_locked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerChain(TypedDict, total=False):
    id: str
    chain_code: str
    legal_name: str
    priority_tier: str
    credit_status: str
    fill_rate_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SupplyAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    spec_id: str
    weekly_contracted_cases: int
    price_per_case_cents: int
    term_start: str
    term_end: str
    pinned_spec_version: Optional[int]
    spec_stale: bool
    under_sla_review: bool
    current_week_allocation_cases: int
    lifetime_released_cases: int
    lifetime_shipped_cases: int
    released_unshipped_cases: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    line_id: str
    spec_id: str
    agreement_id: str
    input_lot_ids: List[str]
    scheduled_start: str
    scheduled_end: str
    cut_family: str
    total_input_cwt: float
    actual_cases: Optional[int]
    rework_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ByproductBatch(TypedDict, total=False):
    # PRD §2.4: carries only id and created_at — no updated_at, no version.
    id: str
    source_lot_id: Optional[str]
    source_run_id: Optional[str]
    stream: str
    routing: str
    weight_cwt: float
    unit_revenue_cents_per_cwt: int
    total_revenue_cents: int
    created_at: str


class ShipmentLine(TypedDict):
    run_id: str
    cases: int


class Shipment(TypedDict, total=False):
    id: str
    agreement_id: str
    carrier_name: str
    trailer_setpoint_f: float
    route_type: str
    lines: List[ShipmentLine]
    cases_shipped: int
    max_transit_temp_f: Optional[float]
    minutes_above_setpoint: Optional[int]
    excursion_flag: bool
    invoice_cents: Optional[int]
    credit_memo_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShortageEvent(TypedDict, total=False):
    id: str
    scope_variety: str
    declared_deficit_cwt: float
    available_week_cases: int
    response_mode: str
    status: str
    allocation_results: Optional[List[Dict[str, Any]]]
    created_at: str
    updated_at: str
    version: int
