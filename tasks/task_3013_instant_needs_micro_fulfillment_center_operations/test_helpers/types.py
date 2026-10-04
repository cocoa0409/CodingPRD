"""Domain types: entity TypedDicts, status enums, role enum (Instant-Needs MFC)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class SiteStatus(str, Enum):
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"


class EffectiveStatus(str, Enum):
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    OPENED_REPLENISH = "OPENED_REPLENISH"


class ProductClass(str, Enum):
    STANDARD = "STANDARD"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    PERISHABLE = "PERISHABLE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StockLotStatus(str, Enum):
    FRESH = "FRESH"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ReplenishOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    PICKING = "PICKING"
    AWAITING_HANDOFF = "AWAITING_HANDOFF"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    HANDOFF_FAILED = "HANDOFF_FAILED"
    CANCELLED = "CANCELLED"


class PickBatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    CLOSED = "CLOSED"


class PickerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DriverStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"
    SUSPENDED = "SUSPENDED"


class DeliveryStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class HandoffStatus(str, Enum):
    NONE = "NONE"
    ID_SCANNED = "ID_SCANNED"
    AGE_VERIFIED = "AGE_VERIFIED"
    REFUSED = "REFUSED"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PICKER = "Picker"
    DRIVER = "Driver"
    SITE_OPS = "SiteOps"


class Site(TypedDict, total=False):
    id: str
    code: str
    name: str
    delivery_radius_miles: float
    fee_schedule: Dict[str, Any]
    fee_waiver_threshold_cents: int
    batch_max_lines: int
    batch_max_items: int
    expiry_horizon_days: int
    peak_windows: List[Dict[str, Any]]
    status: str
    effective_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    price_cents: int
    product_class: str
    restricted: bool
    perishable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryBalance(TypedDict, total=False):
    id: str
    site_id: str
    product_id: str
    on_hand: int
    reserved: int
    min_par_level: int
    on_order: int
    created_at: str
    updated_at: str
    version: int


class StockLot(TypedDict, total=False):
    id: str
    site_id: str
    product_id: str
    lot_code: str
    received_qty: int
    remaining_qty: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    customer_id: str
    tier: str
    status: str
    monthly_fee_cents: int
    current_period_start: str
    current_period_end: str
    periods_paid: int
    period_orders_count: int
    period_credit_earned_cents: int
    auto_renew: bool
    tenure_discount_bps: int
    created_at: str
    updated_at: str
    version: int


class ReplenishOrder(TypedDict, total=False):
    id: str
    site_id: str
    reference: str
    lines: List[Dict[str, Any]]
    expected_at: str
    status: str
    idempotency_key: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    site_id: str
    lines: List[Dict[str, Any]]
    delivery_distance_miles: float
    contains_age_restricted: bool
    subtotal_cents: int
    tax_cents: int
    delivery_fee_cents: int
    loyalty_credit_applied_cents: int
    total_cents: int
    pick_batch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PickBatch(TypedDict, total=False):
    id: str
    site_id: str
    picker_id: str
    order_ids: List[str]
    total_items: int
    sealed_at: Optional[str]
    sealed_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Picker(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    max_run_orders: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryBag(TypedDict, total=False):
    id: str
    order_id: str
    driver_id: Optional[str]
    assigned_at: Optional[str]
    delivery_status: str
    handoff_status: str
    scanned_id_last4: Optional[str]
    created_at: str
    updated_at: str
    version: int
