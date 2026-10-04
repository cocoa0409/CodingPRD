"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    MILL_PLANNER = "MillPlanner"
    BRANCH_MANAGER = "BranchManager"
    CREDIT_MANAGER = "CreditManager"
    ACCOUNT_MANAGER = "AccountManager"
    FLEET_COORDINATOR = "FleetCoordinator"
    BUILDER_CONTACT = "BuilderContact"


class ProductFamily(str, Enum):
    I_JOIST = "I_JOIST"
    LVL_BEAM = "LVL_BEAM"
    GLULAM_BEAM = "GLULAM_BEAM"
    STRUCTURAL_PANEL = "STRUCTURAL_PANEL"


class Species(str, Enum):
    DOUGLAS_FIR = "DOUGLAS_FIR"
    SOUTHERN_PINE = "SOUTHERN_PINE"
    SPRUCE_PINE_FIR = "SPRUCE_PINE_FIR"


class PlacementDifficulty(str, Enum):
    STANDARD = "STANDARD"
    TIGHT_ACCESS = "TIGHT_ACCESS"
    CRANE_ASSIST = "CRANE_ASSIST"


class PricingWeekMode(str, Enum):
    LOCK_AT_ACCEPT = "LOCK_AT_ACCEPT"
    FLOAT_TO_SHIP = "FLOAT_TO_SHIP"


class PriceBasis(str, Enum):
    FIXED = "FIXED"
    INDEX = "INDEX"


class CreditDecision(str, Enum):
    APPROVE = "APPROVE"
    SUSPEND = "SUSPEND"
    CLOSE = "CLOSE"


class DeliveryOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED_ACCESS = "FAILED_ACCESS"


class WeekStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LotStatus(str, Enum):
    ON_HAND = "ON_HAND"
    DEPLETED = "DEPLETED"
    SOLD_OUT = "SOLD_OUT"


class CreditStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TakeoffStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ON_HOLD = "ON_HOLD"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED_ACCESS = "FAILED_ACCESS"
    CANCELLED = "CANCELLED"


class LienStatus(str, Enum):
    FILED = "FILED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MillCapacityWeek(TypedDict, total=False):
    id: str
    mill_code: str
    week_start_date: str
    total_capacity_mbf: int
    internal_alloc_mbf: int
    market_alloc_mbf: int
    committed_internal_mbf: int
    committed_market_mbf: int
    internal_grants: list
    fill_rate_pct: float
    week_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku_code: str
    product_family: str
    species: str
    dimension_label: str
    specialty_flag: bool
    requires_code_report: bool
    requires_design_support: bool
    index_premium_cents: int
    created_at: str
    updated_at: str
    version: int


class PriceIndexEntry(TypedDict, total=False):
    id: str
    product_family: str
    species: str
    effective_week_start: str
    index_price_cents_per_mbf: int
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict, total=False):
    id: str
    branch_code: str
    region_code: str
    species_preference: str
    target_stock_mbf: int
    activity_score: int
    replenishment_enabled: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    branch_id: str
    product_id: str
    qty_received_mbf: int
    unit_cost_cents_per_mbf: int
    received_at: str
    qty_available_mbf: int
    qty_reserved_mbf: int
    qty_sold_mbf: int
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class Builder(TypedDict, total=False):
    id: str
    legal_name: str
    lien_rights_state_code: str
    credit_status: str
    credit_limit_cents: int
    exposure_committed_cents: int
    exposure_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class BuilderJob(TypedDict, total=False):
    id: str
    builder_id: str
    job_name: str
    access_window_start: str
    access_window_end: str
    placement_difficulty: str
    job_exposure_cap_cents: int
    last_completed_delivery_date: Optional[str]
    exposure_committed_cents: int
    exposure_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class TakeoffRequest(TypedDict, total=False):
    id: str
    job_id: str
    plan_reference: str
    includes_floor_system_design: bool
    takeoff_status: str
    design_package_reference: Optional[str]
    quoted_total_cents: Optional[int]
    quoted_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    job_id: str
    branch_id: str
    takeoff_request_id: Optional[str]
    pricing_week_mode: str
    code_report_reference: Optional[str]
    lines: list
    order_status: str
    order_total_cents: int
    delivered_total_cents: int
    priced_week_start: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    sales_order_id: str
    boom_required: bool
    window_start: str
    window_end: str
    delivery_status: str
    truck_shift_id: Optional[str]
    delivery_fee_cents: Optional[int]
    fail_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TruckShift(TypedDict, total=False):
    id: str
    fleet_code: str
    shift_date: str
    window_start: str
    window_end: str
    boom_capable: bool
    max_drops: int
    booked_drops: int
    shift_status: str
    created_at: str
    updated_at: str
    version: int


class LienFiling(TypedDict, total=False):
    id: str
    job_id: str
    lien_status: str
    amount_cents: int
    filed_at: str
    deadline_date: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
