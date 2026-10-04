"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every resource carries id, created_at, updated_at, version.
"""
from enum import Enum
from typing import Optional, TypedDict


class ArticleCategory(str, Enum):
    FURNITURE = "FURNITURE"
    FOOD = "FOOD"
    ACCESSORY = "ACCESSORY"


class PickPolicy(str, Enum):
    SELF_SERVE = "SELF_SERVE"
    FULL_SERVE = "FULL_SERVE"


class MemberStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    NONE = "NONE"
    WAITLISTED = "WAITLISTED"
    SCHEDULED = "SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"


class AssemblyStatus(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class FulfillmentChannel(str, Enum):
    CARRYOUT = "CARRYOUT"
    DELIVERY = "DELIVERY"


class FulfillmentMode(str, Enum):
    SELF_PICK = "SELF_PICK"
    PICKUP_COUNTER = "PICKUP_COUNTER"


class ReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SlotZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"


class SlotPosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AccessType(str, Enum):
    ELEVATOR = "ELEVATOR"
    WALKUP_LOW = "WALKUP_LOW"
    WALKUP_HIGH = "WALKUP_HIGH"


class JobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SHIPPED = "SHIPPED"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    GRADING = "GRADING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class AssemblyState(str, Enum):
    UNOPENED = "UNOPENED"
    PARTIALLY_ASSEMBLED = "PARTIALLY_ASSEMBLED"
    ASSEMBLED = "ASSEMBLED"


class ConditionGrade(str, Enum):
    LIKE_NEW = "LIKE_NEW"
    OPEN_BOX = "OPEN_BOX"
    DAMAGED = "DAMAGED"
    SCRAP = "SCRAP"


class StockSignal(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LOW_STOCK = "LOW_STOCK"
    IN_STOCK = "IN_STOCK"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_OPS = "StoreOps"
    DELIVERY_COORDINATOR = "DeliveryCoordinator"
    ASSEMBLY_PROVIDER = "AssemblyProvider"
    CUSTOMER = "Customer"


class Store(TypedDict, total=False):
    id: str
    name: str
    code: str
    low_stock_threshold: int
    created_at: str
    updated_at: str
    version: int


class Article(TypedDict, total=False):
    id: str
    article_number: str
    name: str
    category: str
    pick_policy: str
    price_cents: int
    family_price_cents: Optional[int]
    lowest_price_365d_cents: Optional[int]
    requires_assembly: bool
    carton_count: int
    is_multi_carton: bool
    created_at: str
    updated_at: str
    version: int


class Carton(TypedDict, total=False):
    id: str
    article_id: str
    carton_seq: int
    aisle: str
    bin: str
    weight_kg: float
    volume_m3: float
    created_at: str
    updated_at: str
    version: int


class BinStock(TypedDict, total=False):
    id: str
    store_id: str
    carton_id: str
    on_hand: int
    reserved: int
    available: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    member_status: str
    member_since: Optional[str]
    points_balance: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    status: str
    delivery_status: str
    assembly_status: str
    fulfillment_channel: str
    subtotal_cents: int
    discount_cents: int
    points_discount_cents: int
    total_cents: int
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    article_id: str
    qty: int
    unit_price_cents: int
    line_gross_cents: int
    line_discount_cents: int
    line_total_cents: int
    effective_unit_paid_cents: int
    fulfillment_mode: str
    returned_qty: int
    created_at: str
    updated_at: str
    version: int


class StockReservation(TypedDict, total=False):
    id: str
    store_id: str
    article_id: str
    customer_id: str
    order_line_id: Optional[str]
    qty: int
    status: str
    reserved_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict, total=False):
    id: str
    store_id: str
    service_date: str
    vehicle_id: str
    zone: str
    capacity_weight_kg: float
    capacity_volume_m3: float
    used_weight_kg: float
    used_volume_m3: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class DeliveryBooking(TypedDict, total=False):
    id: str
    slot_id: str
    order_id: str
    status: str
    access_type: str
    floor: int
    total_weight_kg: float
    total_volume_m3: float
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AssemblyStandard(TypedDict, total=False):
    id: str
    article_id: str
    minutes_per_unit: int
    crew_size: int
    created_at: str
    updated_at: str
    version: int


class AssemblyJob(TypedDict, total=False):
    id: str
    order_id: str
    provider_id: str
    status: str
    window_start: str
    window_end: str
    estimated_minutes: int
    actual_minutes: Optional[int]
    billed_minutes: Optional[int]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SparePartClaim(TypedDict, total=False):
    id: str
    customer_id: str
    article_id: str
    part_number: str
    part_value_cents: int
    reason: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    customer_id: str
    order_id: Optional[str]
    receipted: bool
    status: str
    refund_total_cents: int
    writeoff_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict, total=False):
    id: str
    return_id: str
    article_id: str
    order_line_id: Optional[str]
    qty: int
    assembly_state: str
    condition_grade: Optional[str]
    effective_condition_grade: Optional[str]
    unit_basis_cents: Optional[int]
    refund_cents: Optional[int]
    writeoff_cents: Optional[int]
    restocked_units: int
    created_at: str
    updated_at: str
    version: int
