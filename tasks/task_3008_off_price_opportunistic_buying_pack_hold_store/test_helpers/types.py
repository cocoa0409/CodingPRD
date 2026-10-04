"""Domain types: entity TypedDicts, status enums, role enum for the off-price buying API."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BUYER = "Buyer"
    PLANNING_LEAD = "PlanningLead"
    ALLOCATION_MANAGER = "AllocationManager"
    INVENTORY_PLANNER = "InventoryPlanner"
    PRICING_ANALYST = "PricingAnalyst"
    WAREHOUSE_CLERK = "WarehouseClerk"
    STORE_OPS_LEAD = "StoreOpsLead"
    SHRINK_AUDITOR = "ShrinkAuditor"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DiscretionLevel(str, Enum):
    STANDARD = "STANDARD"
    CONFIDENTIAL = "CONFIDENTIAL"
    QUIET = "QUIET"


class VendorTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class LotType(str, Enum):
    CLOSEOUT = "CLOSEOUT"
    CANCELLATION = "CANCELLATION"
    PACKAWAY = "PACKAWAY"


class LotDisposition(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    PACKAWAY = "PACKAWAY"


class LotStatus(str, Enum):
    OFFERED = "OFFERED"
    EVALUATED = "EVALUATED"
    ACCEPTED = "ACCEPTED"
    PASSED = "PASSED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    VENDOR_PULL = "VENDOR_PULL"
    BUYER_WITHDRAW = "BUYER_WITHDRAW"
    OFFER_EXPIRED = "OFFER_EXPIRED"


class Department(str, Enum):
    APPAREL = "APPAREL"
    HOME = "HOME"
    BEAUTY = "BEAUTY"
    ACCESSORIES = "ACCESSORIES"


class AgeBucket(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"


class HoldStatus(str, Enum):
    STORED = "STORED"
    AGING_REVIEW = "AGING_REVIEW"
    RELEASED = "RELEASED"
    LIQUIDATED = "LIQUIDATED"


class TriggerReason(str, Enum):
    AGING_THRESHOLD = "AGING_THRESHOLD"
    DECISION_KEEP = "DECISION_KEEP"
    DECISION_RELEASE = "DECISION_RELEASE"
    DECISION_LIQUIDATE = "DECISION_LIQUIDATE"


class ClusterCode(str, Enum):
    URBAN_PREMIUM = "URBAN_PREMIUM"
    SUBURBAN_FAMILY = "SUBURBAN_FAMILY"
    VALUE_RURAL = "VALUE_RURAL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class StoreSkuStatus(str, Enum):
    ON_FLOOR = "ON_FLOOR"
    MARKED_DOWN = "MARKED_DOWN"
    CLEARANCE = "CLEARANCE"
    SOLD_OUT = "SOLD_OUT"
    LIQUIDATED = "LIQUIDATED"


class ReceiptStatus(str, Enum):
    OPEN = "OPEN"
    RECEIVED = "RECEIVED"


class ShrinkType(str, Enum):
    UNSCANNED_UNIT = "UNSCANNED_UNIT"
    MIXED_LOT_OVERAGE = "MIXED_LOT_OVERAGE"
    MIXED_LOT_SHORTAGE = "MIXED_LOT_SHORTAGE"
    DAMAGE = "DAMAGE"


class MergeMode(str, Enum):
    FIFO = "FIFO"
    HIGH_VALUE_SORT = "HIGH_VALUE_SORT"


class ShrinkCaseStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class MarkdownEventType(str, Enum):
    CADENCE = "CADENCE"
    FORCE_CLEARANCE = "FORCE_CLEARANCE"


class LiquidationReason(str, Enum):
    CLEARANCE_WEEKS_EXCEEDED = "CLEARANCE_WEEKS_EXCEEDED"
    PACKAWAY_STALE = "PACKAWAY_STALE"


class LiquidationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


# --- Entities with the full common field set (id, created_at, updated_at, version) ---


class MerchandiseSeason(TypedDict, total=False):
    id: str
    season_code: str
    start_date: str
    end_date: str
    department_otb_budget_cents: int
    packaway_reserve_ratio: float
    status: str
    committed_forward_cents: int
    committed_packaway_cents: int
    spent_forward_cents: int
    spent_packaway_cents: int
    over_spend_alert: bool
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    vendor_code: str
    discretion_level: str
    ticket_discretion_required: bool
    default_zone_code: str
    vendor_tier: str
    created_at: str
    updated_at: str
    version: int


class PriceZone(TypedDict, total=False):
    id: str
    zone_code: str
    compare_at_multiplier: float
    markdown_cadence_weeks: int
    clearance_weeks: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    lot_code: str
    vendor_id: str
    season_id: str
    lot_type: str
    disposition: str
    asking_price_cents: int
    mixed_lot: bool
    unit_count: int
    expected_sell_through_pct: float
    estimated_unit_retail_cents: int
    offer_expires_at: str
    target_season_id: Optional[str]
    landed_cost_cents: Optional[int]
    deal_quality_score: Optional[float]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotLine(TypedDict, total=False):
    id: str
    lot_id: str
    style_code: str
    department: str
    quantity: int
    unit_cost_cents: int
    compare_at_claim_cents: int
    target_retail_cents: int
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    warehouse_code: str
    pallet_capacity: int
    zone_code: str
    monthly_holding_rate_per_pallet_cents: int
    created_at: str
    updated_at: str
    version: int


class PackawayHold(TypedDict, total=False):
    id: str
    lot_id: str
    warehouse_id: str
    season_id: str
    target_season_id: str
    pallet_count: int
    entry_date: str
    release_window_start: str
    release_window_end: str
    release_date: Optional[str]
    accrued_holding_cost_cents: int
    review_count: int
    age_bucket: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_code: str
    cluster_code: str
    zone_code: str
    storage_capacity_units: int
    clearance_outlet: bool
    created_at: str
    updated_at: str
    version: int


class AllocationPlan(TypedDict, total=False):
    id: str
    lot_id: str
    season_id: str
    total_units: int
    cluster_weights: dict
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoreSku(TypedDict, total=False):
    id: str
    store_id: str
    lot_line_id: str
    ticket_id: str
    season_id: str
    allocation_plan_id: Optional[str]
    units_on_hand: int
    floor_date: str
    weeks_on_floor: int
    markdown_step: int
    current_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict, total=False):
    id: str
    lot_id: str
    warehouse_id: str
    receipt_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShrinkCase(TypedDict, total=False):
    id: str
    store_id: Optional[str]
    store_sku_id: Optional[str]
    lot_id: Optional[str]
    shrink_type: str
    merge_mode: str
    units_lost: int
    units_untraceable: int
    shrink_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidationOrder(TypedDict, total=False):
    id: str
    store_id: str
    lot_id: str
    reason: str
    recovery_rate_pct: float
    expected_units: int
    actual_units: Optional[int]
    recovery_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entries: ONLY id + created_at (no updated_at, no version) ---


class Ticket(TypedDict, total=False):
    id: str
    lot_line_id: str
    zone_code: str
    ticket_retail_cents: int
    compare_at_cents: Optional[int]
    compare_at_omitted: bool
    vendor_name_on_ticket: bool
    substantiation_notes: str
    status: str
    created_at: str


class ReceiptLine(TypedDict, total=False):
    id: str
    receipt_id: str
    lot_line_id: str
    declared_qty: int
    received_qty: int
    variance_qty: int
    variance_value_cents: int
    extended_cost_cents: int
    created_at: str


class MarkdownEvent(TypedDict, total=False):
    id: str
    store_sku_id: str
    step_number: int
    old_price_cents: int
    new_price_cents: int
    markdown_cents: int
    event_type: str
    effective_date: str
    created_at: str
