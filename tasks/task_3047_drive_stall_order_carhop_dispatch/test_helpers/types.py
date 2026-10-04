"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed fields id, created_at,
updated_at, and version (PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class WeatherMode(str, Enum):
    NORMAL = "NORMAL"
    HEAT_ADVISORY = "HEAT_ADVISORY"
    STORM = "STORM"


class LanePosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    CURBSIDE_ONLY = "CURBSIDE_ONLY"


class MenuCategory(str, Enum):
    FOOD = "FOOD"
    DRINK = "DRINK"
    SLUSH = "SLUSH"
    DESSERT = "DESSERT"
    ADDIN = "ADDIN"


class SizeScheme(str, Enum):
    NONE = "NONE"
    DRINK_SIZES = "DRINK_SIZES"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StallKind(str, Enum):
    STALL = "STALL"
    PATIO = "PATIO"


class StallStatus(str, Enum):
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CarhopZone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    PATIO = "PATIO"


class OrderChannel(str, Enum):
    STALL_INTERCOM = "STALL_INTERCOM"
    APP_CHECKIN = "APP_CHECKIN"
    DRIVE_THRU = "DRIVE_THRU"
    PATIO = "PATIO"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    PREPARING = "PREPARING"
    READY = "READY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class OfferKind(str, Enum):
    HAPPY_HOUR = "HAPPY_HOUR"
    APP_ONLY = "APP_ONLY"
    PROMO = "PROMO"


class DiscountType(str, Enum):
    HALF_PRICE_DRINKS = "HALF_PRICE_DRINKS"
    PERCENT_OFF_ORDER = "PERCENT_OFF_ORDER"
    FIXED_OFF_CENTS = "FIXED_OFF_CENTS"


class OfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class DeliveryRunStatus(str, Enum):
    LOADED = "LOADED"
    OUT = "OUT"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class TipRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class FaultKind(str, Enum):
    INTERCOM_DEAD = "INTERCOM_DEAD"
    PAYMENT_TERMINAL_DEAD = "PAYMENT_TERMINAL_DEAD"
    MENU_BOARD_DEAD = "MENU_BOARD_DEAD"


class FaultStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SHIFT_MANAGER = "ShiftManager"
    KITCHEN_STAFF = "KitchenStaff"
    CARHOP = "Carhop"
    CUSTOMER = "Customer"


class Location(TypedDict, total=False):
    id: str
    code: str
    name: str
    timezone: str
    weather_mode: str
    stall_capacity: int
    stalls_available: int
    lane_posture: str
    rush_index: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    base_price_cents: int
    size_scheme: str
    half_price_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomizationOption(TypedDict, total=False):
    id: str
    code: str
    applies_to_category: str
    price_cents: int
    is_size: bool
    size_upcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    app_user: bool
    stored_tip_default_pct: float
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict, total=False):
    id: str
    location_id: str
    stall_number: int
    kind: str
    intercom_functional: bool
    status: str
    current_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Carhop(TypedDict, total=False):
    id: str
    location_id: str
    name: str
    zone: str
    on_shift: bool
    max_trays: int
    active_run_load: int
    tips_outstanding_cents: int
    tips_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    location_id: str
    stall_id: Optional[str]
    customer_id: Optional[str]
    channel: str
    status: str
    payment_status: str
    checked_in_at: Optional[str]
    placed_at: Optional[str]
    ready_at: Optional[str]
    delivered_at: Optional[str]
    service_target_seconds: Optional[int]
    late_flag: bool
    subtotal_cents: int
    offer_discount_cents: int
    tax_cents: int
    tip_cents: int
    total_cents: int
    total_tendered_cents: int
    delivery_run_id: Optional[str]
    run_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    menu_item_id: str
    quantity: int
    size_option_code: Optional[str]
    addin_option_codes: List[str]
    unit_price_cents: int
    extended_price_cents: int
    happy_hour_priced: bool
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    location_id: str
    code: str
    kind: str
    discount_type: str
    discount_value: int
    window_start_local: str
    window_end_local: str
    app_only: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRun(TypedDict, total=False):
    id: str
    location_id: str
    carhop_id: str
    status: str
    order_count: int
    staged_at: str
    out_at: Optional[str]
    route_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TipRecord(TypedDict, total=False):
    id: str
    order_id: str
    carhop_id: Optional[str]
    tip_cents: int
    status: str
    adjusted_tip_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EquipmentFault(TypedDict, total=False):
    id: str
    stall_id: str
    reported_by_role: str
    kind: str
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTargetProfile(TypedDict, total=False):
    id: str
    location_id: str
    channel: str
    weather_mode: str
    target_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int
