"""Domain types: entity TypedDicts, status enums, role enum.

Every one of the twelve resources carries common_fields semantics (id,
created_at, updated_at, version) per the PRD's identity section.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ASSORTMENT_PLANNER = "AssortmentPlanner"
    BOUTIQUE_MANAGER = "BoutiqueManager"
    RETAIL_LEAD = "RetailLead"
    RETAIL_CASHIER = "RetailCashier"
    CASHIER = "Cashier"
    SERVER = "Server"
    ANONYMOUS = "Anonymous"


class RecognitionPolicy(str, Enum):
    FINAL_ONLY = "FINAL_ONLY"
    PROVISIONAL_THEN_FINAL = "PROVISIONAL_THEN_FINAL"


class FiscalPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RegionCode(str, Enum):
    NORTHEAST = "NORTHEAST"
    SOUTHEAST = "SOUTHEAST"
    MIDWEST = "MIDWEST"
    SOUTHWEST = "SOUTHWEST"
    WEST = "WEST"


class AssortmentTier(str, Enum):
    FULL = "FULL"
    REGIONAL_TWEAK = "REGIONAL_TWEAK"
    MINIMAL = "MINIMAL"


class StoreDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TrafficState(str, Enum):
    QUIET = "QUIET"
    STEADY = "STEADY"
    RUSH = "RUSH"


class ConversionGate(str, Enum):
    OPEN = "OPEN"
    GATED_RESTRICTED = "GATED_RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARANCE = "CLEARANCE"
    DISCONTINUED = "DISCONTINUED"


class ThemeCode(str, Enum):
    HARVEST = "HARVEST"
    WINTER_HOLIDAY = "WINTER_HOLIDAY"
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    NOSTALGIA_CLASSIC = "NOSTALGIA_CLASSIC"


class ReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class CheckStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    GIFT_CARD = "GIFT_CARD"
    SPLIT = "SPLIT"


class LineKind(str, Enum):
    RETAIL = "RETAIL"
    SEASONAL_DECOR = "SEASONAL_DECOR"
    NOSTALGIA = "NOSTALGIA"
    GIFT_CARD = "GIFT_CARD"


class RestaurantShareBasis(str, Enum):
    CHECK_TOTAL = "CHECK_TOTAL"
    ALLOCATED = "ALLOCATED"


class ClearanceStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    LIQUIDATED = "LIQUIDATED"
    CANCELLED = "CANCELLED"


class ClearanceStage(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Workcode(str, Enum):
    SERVER = "SERVER"
    COOK = "COOK"
    CASHIER = "CASHIER"
    RETAIL_STOCK = "RETAIL_STOCK"
    RETAIL_CASHIER = "RETAIL_CASHIER"
    RETAIL_GIFT = "RETAIL_GIFT"


class TransferStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    VOID_RECEIVING = "VOID_RECEIVING"


class ReceivingZone(str, Enum):
    BACKROOM = "BACKROOM"
    FOOD_STORAGE = "FOOD_STORAGE"


class ReadingSource(str, Enum):
    RECEIVING = "RECEIVING"
    SALES_FLOOR_MOVE = "SALES_FLOOR_MOVE"
    CYCLE_COUNT = "CYCLE_COUNT"


class PlanogramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class SlotStatus(str, Enum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    FROZEN = "FROZEN"
    VACATED = "VACATED"


# --------------------------------------------------------------------------
# Entity shapes (common_fields: true on every resource)
# --------------------------------------------------------------------------

class Brand(TypedDict, total=False):
    id: str
    brand_code: str
    legal_name: str
    retail_recognition_policy: str
    liquidation_trigger_rpg_cents: int
    open_receipt_grace_hours: int
    transfer_variance_tolerance_bps: int
    waiting_area_retail_weight_bps: int
    tip_minimum_minutes: int
    clearance_buffer_hours: int
    food_storage_corridor_units: int
    max_check_total_cents: int
    fiscal_period: str
    fiscal_period_status: str
    provisional_retail_revenue_cents: int
    recognized_retail_revenue_cents: int
    brand_retail_sales_per_guest_cents: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict, total=False):
    id: str
    brand_id: str
    store_number: str
    region_code: str
    assortment_tier: str
    backroom_capacity_units: int
    clearance_max_active: int
    local_event_codes: List[str]
    backroom_occupancy_units: int
    backroom_committed_units: int
    food_storage_units: int
    staging_free_units: int
    active_clearance_count: int
    active_planogram_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoreDay(TypedDict, total=False):
    id: str
    location_id: str
    business_date: str
    traffic_state: str
    conversion_gate: str
    day_status: str
    restaurant_guest_count: int
    restaurant_sales_cents: int
    waiting_area_shopper_count: int
    waiting_area_converted_count: int
    retail_transaction_count: int
    retail_sales_cents: int
    retail_sales_per_guest_cents: int
    provisional_retail_sales_per_guest_cents: int
    waiting_area_conversion_index_bps: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    sku: str
    name: str
    theme_code: str
    nostalgia_flag: bool
    unit_retail_cents: int
    unit_cost_cents: int
    import_lead_time_days: int
    status: str
    current_markdown_pct: float
    effective_price_cents: int
    compounded_price_cents: int
    on_hand_units: int
    order_deadline_reached: bool
    clearance_week: int
    created_at: str
    updated_at: str
    version: int


class PlanogramVersion(TypedDict, total=False):
    id: str
    location_id: str
    assortment_tier: str
    effective_date: str
    status: str
    superseded_by_version_id: Optional[str]
    slot_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanogramSlot(TypedDict, total=False):
    id: str
    planogram_version_id: str
    item_id: str
    slot_position: int
    facings: int
    min_presentation_units: int
    status: str
    applied_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestCheck(TypedDict, total=False):
    id: str
    location_id: str
    store_day_id: str
    table_number: str
    restaurant_guest_count: int
    restaurant_subtotal_cents: int
    retail_subtotal_cents: int
    service_fee_cents: int
    total_cents: int
    check_status: str
    settlement_status: str
    presented_shift_id: str
    tip_cents: int
    tip_eligible: bool
    tip_pct: float
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict, total=False):
    id: str
    location_id: str
    store_day_id: str
    guest_check_id: Optional[str]
    receipt_number: str
    lines: List[dict]
    restaurant_share_cents: int
    restaurant_share_basis: str
    payment_method: str
    status: str
    provisional_retail_cents: int
    recognized_retail_cents: int
    recognition_delta_cents: int
    reconciliation_posted_at: Optional[str]
    reversal_posted_at: Optional[str]
    reconciled_at: Optional[str]
    settled_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearanceSchedule(TypedDict, total=False):
    id: str
    location_id: str
    item_id: str
    start_date: str
    end_date: str
    stage: str
    markdown_pct: float
    liquidation_price_cents: int
    status: str
    remaining_units: int
    liquidated_units: int
    liquidation_bucket_units: List[int]
    liquidation_blended_cents: int
    extension_count: int
    reactivation_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict, total=False):
    id: str
    location_id: str
    employee_id: str
    start_utc: str
    end_utc: str
    workcode: str
    tip_eligible_claim: bool
    tip_eligible: bool
    tip_eligible_minutes: int
    status: str
    crossover_authorized_by_shift_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict, total=False):
    id: str
    location_id: str
    store_day_id: str
    item_id: str
    declared_units: int
    received_units: int
    receiving_zone: str
    status: str
    variance_units: int
    variance_bps: int
    dispatched_at: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackroomCapacityReading(TypedDict, total=False):
    id: str
    location_id: str
    store_day_id: str
    trigger_transfer_id: Optional[str]
    measured_at: str
    backroom_units: int
    food_storage_units: int
    dated_units: int
    source: str
    occupancy_units: int
    committed_units: int
    free_units: int
    capacity_breach: bool
    created_at: str
    updated_at: str
    version: int