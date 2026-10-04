"""Domain types: entity TypedDicts, status enums and the role enum.

Every enumeration value below is the exact string literal the PRD declares.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role names (PRD 2.1) -- spelled exactly as the API requires them.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMMERCIAL_SALES_REP = "CommercialSalesRep"
    DELIVERY_DRIVER = "DeliveryDriver"
    TOOL_CRIB_ATTENDANT = "ToolCribAttendant"
    CREDIT_ANALYST = "CreditAnalyst"
    ROUTE_DISPATCHER = "RouteDispatcher"
    PARTS_CATEGORY_MANAGER = "PartsCategoryManager"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class AccountPosture(str, Enum):
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    CREDIT_SUSPENDED = "CREDIT_SUSPENDED"
    CLOSED = "CLOSED"


class PricingTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class DeliveryServiceLevel(str, Enum):
    DELIVERY_DESK = "DELIVERY_DESK"
    SHOP_DELIVERY = "SHOP_DELIVERY"
    HUB_DAILY = "HUB_DAILY"
    HOTSHOT = "HOTSHOT"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    VOID = "VOID"


class PricingBand(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class FulfillmentRoute(str, Enum):
    STORE = "STORE"
    HUB = "HUB"
    MEGA_HUB = "MEGA_HUB"
    DC = "DC"
    UNROUTABLE = "UNROUTABLE"


class StoreType(str, Enum):
    SATELLITE = "SATELLITE"
    HUB = "HUB"
    MEGA_HUB = "MEGA_HUB"
    DC = "DC"


class CatalogState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CHECKED_OUT = "CHECKED_OUT"
    IN_USE = "IN_USE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    INSPECTED = "INSPECTED"
    CLOSED = "CLOSED"
    FORFEITED = "FORFEITED"


class LoanDepositState(str, Enum):
    UNCHARGED = "UNCHARGED"
    HELD = "HELD"
    APPLIED_TO_BALANCE = "APPLIED_TO_BALANCE"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    WORN = "WORN"
    BROKEN = "BROKEN"
    LOST = "LOST"


class WearBand(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"


class ToolPlacement(str, Enum):
    FRONT = "FRONT"
    REAR_LEFT = "REAR_LEFT"
    REAR_RIGHT = "REAR_RIGHT"
    OTHER = "OTHER"


class CoreReturnStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_TRANSIT = "IN_TRANSIT"
    INSPECTED = "INSPECTED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    SEQUENCED = "SEQUENCED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    MISSED = "MISSED"
    REJECTED = "REJECTED"


class StopKind(str, Enum):
    CUSTOMER = "CUSTOMER"
    RETURN_DESK = "RETURN_DESK"


class DriverType(str, Enum):
    OWNED = "OWNED"
    AFFILIATE = "AFFILIATE"


class CoveragePosture(str, Enum):
    ACTIVE = "ACTIVE"
    SCHEDULED = "SCHEDULED"
    EXPIRED = "EXPIRED"


class DriveType(str, Enum):
    FWD = "FWD"
    RWD = "RWD"
    AWD = "AWD"
    FOUR_WD = "FOUR_WD"
    ANY = "ANY"


# ---------------------------------------------------------------------------
# Entity shapes.
#
# CommercialAccount, Vehicle, Part, Store, InventoryItem, SalesRep,
# RepCoverage, PartOrder, ToolLoan, ToolCatalog, CoreReturn, RouteStop and
# ServiceRoute share the audit spine (id, created_at, updated_at, version).
# ToolFitment, PartInterchange, PartFitment and WarrantyRegistration are the
# deliberately slimmer child records: only id and created_at.
# ---------------------------------------------------------------------------
class CommercialAccount(TypedDict):
    id: str
    shop_name: str
    tax_id: str
    billing_address: str
    shipping_address: Optional[str]
    home_store_id: str
    credit_limit_cents: int
    credit_terms_days: int
    tier: str
    delivery_service_level: str
    petty_cash_cents: int
    credit_exposure_cents: int
    deposit_liability_cents: int
    receivable_balance_cents: int
    account_posture: str
    next_cutoff_at: Optional[str]
    order_sequence: int
    is_archived: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    vin: str
    year: int
    make: str
    model: str
    engine_code: str
    drive_type: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    sku: str
    description: str
    line_code: str
    list_price_cents: int
    core_charge_cents: int
    is_hazardous: bool
    is_returnable: bool
    is_archived: bool
    superseded_by_part_id: Optional[str]
    supersession_depth: int
    catalog_state: str
    created_at: str
    updated_at: str
    version: int


class ToolFitment(TypedDict):
    id: str
    tool_catalog_id: str
    part_id: str
    placement: str
    depth_index: int
    created_at: str


class PartInterchange(TypedDict):
    id: str
    part_id: str
    interchange_sku: str
    interchange_brand: str
    created_at: str


class PartFitment(TypedDict):
    id: str
    part_id: str
    year_from: int
    year_to: int
    make: str
    model: str
    engine_code: str
    drive_type: str
    created_at: str


class Store(TypedDict):
    id: str
    store_code: str
    name: str
    store_type: str
    hub_store_id: Optional[str]
    delivery_radius_miles: float
    cutoff_hour_local: int
    cutoff_buffer_minutes: int
    promise_time_minutes: int
    daily_capacity_units: int
    committed_units_today: int
    capacity_epoch_at: str
    is_archived: bool
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    store_id: str
    part_id: str
    on_hand_units: int
    reserved_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class SalesRep(TypedDict):
    id: str
    email: str
    full_name: str
    district_code: str
    home_store_id: str
    active_account_count: int
    created_at: str
    updated_at: str
    version: int


class RepCoverage(TypedDict):
    id: str
    rep_id: str
    account_id: str
    effective_from: str
    effective_to: str
    coverage_posture: str
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    account_id: str
    vehicle_id: Optional[str]
    line_items: List[dict]
    member_sequence: int
    service_route_id: Optional[str]
    fulfillment_route: str
    reserved_unit_count: int
    pricing_band: str
    parts_subtotal_cents: int
    core_charge_total_cents: int
    tier_discount_cents: int
    refundable_deposit_cents: int
    delivery_fee_cents: int
    promised_at: Optional[str]
    delivered_at: Optional[str]
    delivered_payment_due_at: Optional[str]
    refundable_deposit_consumed_cents: int
    order_base_cents: int
    satisfaction_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolLoan(TypedDict):
    id: str
    account_id: str
    tool_catalog_id: str
    loaned_order_id: Optional[str]
    deposit_amount_cents: int
    deposit_state: str
    loaned_at: Optional[str]
    due_at: Optional[str]
    returned_at: Optional[str]
    overdue_days: int
    return_condition: Optional[str]
    deposit_forfeited_cents: int
    replacement_part_id: Optional[str]
    wear_intensity: float
    damage_multiplier: float
    forfeiture_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolCatalog(TypedDict):
    id: str
    tool_sku: str
    tool_name: str
    deposit_amount_cents: int
    replacement_part_id: Optional[str]
    replacement_unit_cost_cents: int
    wear_accumulated: float
    wear_band: str
    wear_multiplier_rate: float
    wear_forfeiture_rate: float
    wear_grace_period_hours: int
    created_at: str
    updated_at: str
    version: int


class CoreReturn(TypedDict):
    id: str
    order_id: str
    account_id: str
    line_items: List[dict]
    core_subtotal_cents: int
    restocking_fee_cents: int
    warranty_covered: bool
    credit_amount_cents: int
    ordered_quantity_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict):
    id: str
    account_id: str
    part_id: str
    purchase_order_id: Optional[str]
    purchased_at: str
    warranty_expires_at: str
    claim_reference: Optional[str]
    created_at: str


class RouteStop(TypedDict):
    id: str
    route_id: str
    stop_sequence: Optional[int]
    account_id: str
    order_ids: List[str]
    delivery_window_start: str
    delivery_window_end: str
    travel_minutes_from_previous: int
    drop_minutes: int
    projected_arrival_at: Optional[str]
    projected_departure_at: Optional[str]
    lateness_minutes: int
    stop_kind: str
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRoute(TypedDict):
    id: str
    route_code: str
    service_date: str
    driver_id: str
    driver_type: str
    departure_at: str
    shift_end_at: str
    return_at: Optional[str]
    effective_departure_at: Optional[str]
    total_miles: float
    run_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int