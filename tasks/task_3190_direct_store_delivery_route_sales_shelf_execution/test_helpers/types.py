"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. Entities with common fields carry
id + created_at + updated_at + version; the OrderLine sub-record carries
only id + created_at.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ROUTE_SUPERVISOR = "RouteSupervisor"
    ROUTE_SALES_REP = "RouteSalesRep"
    STORE_MANAGER = "StoreManager"


class RepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StoreFormat(str, Enum):
    CONVENIENCE = "CONVENIENCE"
    GROCERY = "GROCERY"
    SUPERCENTER = "SUPERCENTER"
    DOLLAR = "DOLLAR"


class CreditPolicy(str, Enum):
    FULL_RETAIL = "FULL_RETAIL"
    SALVAGE_RATE = "SALVAGE_RATE"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PerformanceFlag(str, Enum):
    CLEAR = "CLEAR"
    PERFORMANCE_WATCH = "PERFORMANCE_WATCH"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class RouteDayStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    IN_PROGRESS = "IN_PROGRESS"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    SEALED = "SEALED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    STANDARD = "STANDARD"
    EVENT_SURGE = "EVENT_SURGE"


class ShelfExecutionStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class StaleCreditStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PricingVariant(str, Enum):
    FULL_RETAIL = "FULL_RETAIL"
    SALVAGE_RATE = "SALVAGE_RATE"


class PromoAgreementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    EXPIRED = "EXPIRED"


class DisplayType(str, Enum):
    ENDCAP = "ENDCAP"
    AISLE = "AISLE"
    DUMP_BIN = "DUMP_BIN"
    COUNTER = "COUNTER"


class PromoExecutionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    DISPUTED = "DISPUTED"
    POSTED = "POSTED"


class ServiceGrade(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class RouteSalesRepresentative(TypedDict, total=False):
    id: str
    full_name: str
    home_depot: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_code: str
    name: str
    format: str
    credit_policy: str
    delivery_window_start_minute: int
    delivery_window_end_minute: int
    store_credit_cap_cents: int
    promo_rebate_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    case_price_cents: int
    shelf_life_days: int
    promo_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    territory_code: str
    rsr_id: str
    base_capacity_cases: int
    truck_cap_cases: int
    performance_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStoreAssignment(TypedDict, total=False):
    id: str
    route_id: str
    store_id: str
    service_weekdays: List[str]
    stop_sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict, total=False):
    id: str
    route_id: str
    service_date: str
    is_event_day: bool
    event_surge_cases: int
    capacity_cases: int
    loaded_cases: int
    delivered_cases: int
    stale_pulled_cases: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckInventoryLot(TypedDict, total=False):
    id: str
    route_day_id: str
    product_id: str
    lot_code: str
    expiration_date: str
    loaded_cases: int
    delivered_cases: int
    stale_pulled_cases: int
    returned_cases: int
    remaining_cases: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreOrder(TypedDict, total=False):
    id: str
    route_day_id: str
    store_id: str
    order_type: str
    status: str
    gross_total_cents: int
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    # Immutable sub-record: only id + created_at are common fields.
    id: str
    order_id: str
    product_id: str
    qty_ordered_cases: int
    line_discount_pct: float
    qty_delivered_cases: int
    line_total_cents: int
    line_seq: int
    created_at: str


class ShelfExecution(TypedDict, total=False):
    id: str
    route_day_id: str
    store_id: str
    product_id: str
    qty_placed_cases: int
    rotated: bool
    display_built: bool
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaleCredit(TypedDict, total=False):
    id: str
    route_day_id: str
    store_id: str
    product_id: str
    lot_id: str
    qty_cases: int
    pricing_variant: str
    credit_cents: int
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromoAgreement(TypedDict, total=False):
    id: str
    store_id: str
    product_id: str
    window_start: str
    window_end: str
    display_type: str
    rebate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PromoExecution(TypedDict, total=False):
    id: str
    agreement_id: str
    route_day_id: str
    photo_url: str
    built_by_user_id: str
    verified_by_user_id: Optional[str]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteSettlement(TypedDict, total=False):
    id: str
    route_day_id: str
    status: str
    gross_delivered_cents: int
    credits_cents: int
    forward_expected_cents: int
    chronological_expected_cents: int
    recon_delta_cents: int
    cash_collected_cents: Optional[int]
    variance_cents: Optional[int]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceLevelSnapshot(TypedDict, total=False):
    id: str
    route_id: str
    period_start: str
    period_end: str
    orders_count: int
    fill_rate: float
    oos_rate: float
    service_grade: str
    stale_ratio: float
    performance_flag_result: str
    created_at: str
    updated_at: str
    version: int
