"""Domain types: entity TypedDicts, status enums, role enum.

All primary resources carry id, created_at, updated_at, version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    CANCELLED_REFUNDED = "CANCELLED_REFUNDED"


class TradeAccountStatus(str, Enum):
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TradeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LineKind(str, Enum):
    STOCK = "STOCK"
    CUSTOM = "CUSTOM"


class SourceBookStatus(str, Enum):
    IN_PRINT = "IN_PRINT"
    RELEASED = "RELEASED"
    ARCHIVED = "ARCHIVED"


class OrderStatus(str, Enum):
    QUOTE = "QUOTE"
    CONFIRMED = "CONFIRMED"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PricingTier(str, Enum):
    TRADE = "TRADE"
    MEMBER = "MEMBER"
    RETAIL = "RETAIL"


class FabricTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ProductionStatus(str, Enum):
    NONE = "NONE"
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    COMMITTED = "COMMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETE = "COMPLETE"
    RELEASED = "RELEASED"


class ProductionSlotStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    CONSUMED = "CONSUMED"


class ConsultationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RESCHEDULED = "RESCHEDULED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    Member = "Member"
    TradeDesigner = "TradeDesigner"
    GalleryAssociate = "GalleryAssociate"
    TradeReviewer = "TradeReviewer"
    ProductionPlanner = "ProductionPlanner"
    HubOperator = "HubOperator"
    PlatformAdmin = "PlatformAdmin"


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    auto_renew: bool
    status: str
    current_period_start: str
    current_period_end: str
    grace_end: Optional[str]
    fee_paid_total_cents: int
    lifetime_gross_savings_cents: int
    lifetime_net_savings_cents: int
    pricing_tier: str
    created_at: str
    updated_at: str
    version: int


class TradeAccount(TypedDict, total=False):
    id: str
    email: str
    business_name: str
    credential_document_id: str
    license_number: str
    status: str
    tier: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Gallery(TypedDict, total=False):
    id: str
    name: str
    region: str
    daily_route_minutes_capacity: int
    booked_route_minutes: Dict[str, int]
    reserved_production_minutes: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    list_price_cents: int
    line_kind: str
    status: str
    promo_active: bool
    created_at: str
    updated_at: str
    version: int


class SourceBook(TypedDict, total=False):
    id: str
    title: str
    product_ids: List[str]
    print_ready_date: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    gallery_id: str
    member_id: Optional[str]
    trade_account_id: Optional[str]
    pricing_tier: str
    status: str
    quote_expires_at: str
    consultation_extensions_used: int
    quote_total_cents: int
    subtotal_cents: int
    white_glove_fee_cents: int
    total_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    confirmed_at: Optional[str]
    delivered_at: Optional[str]
    cancel_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    qty: int
    fabric_tier: str
    unit_list_price_cents: int
    line_charged_cents: int
    production_status: str
    production_slot_id: Optional[str]
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict, total=False):
    id: str
    gallery_id: str
    starts_at: str
    ends_at: str
    status: str
    committed_order_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignConsultation(TypedDict, total=False):
    id: str
    member_id: str
    order_id: str
    scheduled_at: str
    status: str
    design_plan_notes: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict, total=False):
    id: str
    order_id: str
    gallery_id: str
    delivery_date: str
    duration_minutes: int
    room_placement: bool
    assembly_required: bool
    packaging_removed: bool
    status: str
    failure_reason: Optional[str]
    replaced_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    order_id: str
    order_line_ids: List[str]
    status: str
    restocking_fee_cents: int
    refund_cents: int
    reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
