"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.7, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SUPPORT_AGENT = "SupportAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AvailabilityStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DISCONTINUED = "DISCONTINUED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SKIPPED = "SKIPPED"
    AUTO_SKIPPED = "AUTO_SKIPPED"
    SHIPPED = "SHIPPED"
    REFUNDED = "REFUNDED"
    RESHIPPED = "RESHIPPED"


class SkipReason(str, Enum):
    CUSTOMER = "CUSTOMER"
    PRICE_CAP = "PRICE_CAP"
    UNAVAILABLE = "UNAVAILABLE"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    APPROVED_RESHIP = "APPROVED_RESHIP"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class ReshipmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class NotificationType(str, Enum):
    OFFER_CREATED = "OFFER_CREATED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    PRICE_INCREASE = "PRICE_INCREASE"
    PRICE_CAP_SKIP = "PRICE_CAP_SKIP"
    PLAN_SHIPPED = "PLAN_SHIPPED"
    RESHIP_DISPATCHED = "RESHIP_DISPATCHED"


# --- Entity TypedDicts (common-fields entities carry id/created_at/updated_at/version) ---


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    region: str
    preferred_delivery_day: int
    account_status: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    region: str
    subscription_eligible: bool
    discontinued: bool
    substitute_product_id: Optional[str]
    availability_status: str
    current_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PriceEvent(TypedDict):
    """Append-only record: carries ONLY id + created_at (PRD §2.7)."""

    id: str
    product_id: str
    price_cents: int
    effective_from: str
    created_at: str


class InventoryPlacement(TypedDict):
    id: str
    product_id: str
    region: str
    received_total_units: int
    on_hand_units: int
    reserved_units: int
    shipped_units: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    product_id: str
    cadence_months: int
    quantity: int
    start_date: str
    next_delivery_date: str
    status: str
    price_cap_cents: Optional[int]
    subscribe_price_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryPlan(TypedDict):
    id: str
    customer_id: str
    delivery_month: str
    delivery_date: str
    plan_status: str
    active_line_count: int
    tier_discount_pct: float
    estimated_total_cents: int
    charged_total_cents: Optional[int]
    gross_line_total_cents: int
    refunded_total_cents: int
    applied_coupon_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class PlanLine(TypedDict):
    id: str
    plan_id: str
    subscription_id: Optional[str]
    product_id: str
    quantity: int
    is_bonus: bool
    was_substituted: bool
    line_status: str
    skip_reason: Optional[str]
    unit_price_cents: Optional[int]
    line_charged_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    code: str
    discount_type: str
    percent_off: Optional[float]
    flat_off_cents: Optional[int]
    stackable: bool
    min_subtotal_cents: int
    valid_from: str
    valid_to: str
    coupon_status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    bonus_product_id: str
    min_line_count: int
    starts_on: str
    ends_on: str
    promotion_status: str
    created_at: str
    updated_at: str
    version: int


class RetentionOffer(TypedDict):
    id: str
    subscription_id: str
    offer_type: str
    credit_amount_cents: int
    offer_status: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    plan_id: str
    customer_id: str
    damaged_line_ids: List[str]
    claim_status: str
    claim_refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Reshipment(TypedDict):
    id: str
    claim_id: str
    reshipped_line_ids: List[str]
    reshipment_status: str
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    product_id: str
    region: str
    forecast_month: str
    committed_units: int
    provisional_units: int
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    """Append-only record: carries ONLY id + created_at (PRD §2.7)."""

    id: str
    customer_id: str
    notification_type: str
    message: str
    related_plan_id: Optional[str]
    created_at: str
