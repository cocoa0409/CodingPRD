"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE = "CustomerService"
    FINANCE_OPS = "FinanceOps"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RateWindowStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class FraudStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class OfferMode(str, Enum):
    BID = "BID"
    FIXED = "FIXED"


class OpaqueBidStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class FulfillmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SERVICE_FAILED = "SERVICE_FAILED"
    SETTLED = "SETTLED"


class ComplaintCategory(str, Enum):
    PROPERTY_MISREPRESENTED = "PROPERTY_MISREPRESENTED"
    SERVICE_FAILURE = "SERVICE_FAILURE"
    DISSATISFIED_REVEAL = "DISSATISFIED_REVEAL"
    OTHER = "OTHER"


class ComplaintResolution(str, Enum):
    NONE = "NONE"
    GOODWILL_CREDIT = "GOODWILL_CREDIT"
    FULL_REFUND = "FULL_REFUND"


class ComplaintCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class SettlementBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class FraudReasonCode(str, Enum):
    ARBITRAGE_PATTERN = "ARBITRAGE_PATTERN"
    REPEAT_WIN_RATE = "REPEAT_WIN_RATE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# All entities carry common fields: id, created_at, updated_at, version.

class Supplier(TypedDict, total=False):
    id: str
    legal_name: str
    opaque_commission_pct: float
    parity_protection_enabled: bool
    concealment_discount_min_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    supplier_id: str
    brand_name: str
    star_rating: int
    neighborhood_code: str
    amenity_codes: List[str]
    published_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class RateWindow(TypedDict, total=False):
    id: str
    property_id: str
    check_in_date: str
    check_out_date: str
    opaque_rate_cents: int
    rooms_allocated: int
    rooms_sold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureZone(TypedDict, total=False):
    id: str
    neighborhood_code: str
    min_star_rating: int
    revealed_amenity_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    fraud_score: int
    fraud_status: str
    opaque_win_count_30d: int
    created_at: str
    updated_at: str
    version: int


class OpaqueBid(TypedDict, total=False):
    id: str
    customer_id: str
    neighborhood_code: str
    min_star_rating: int
    check_in_date: str
    check_out_date: str
    bid_price_cents: Optional[int]
    offer_mode: str
    computed_price_cents: Optional[int]
    winning_property_id: Optional[str]
    winning_rate_window_id: Optional[str]
    concealment_discount_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    opaque_bid_id: str
    customer_id: str
    property_id: str
    supplier_id: str
    rate_window_id: str
    check_in_date: str
    check_out_date: str
    charged_price_cents: int
    supplier_remittance_cents: int
    platform_commission_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class ComplaintCase(TypedDict, total=False):
    id: str
    booking_id: str
    customer_id: str
    category: str
    description: str
    resolution: str
    goodwill_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    supplier_id: str
    period_start_date: str
    period_end_date: str
    booking_ids: List[str]
    gross_remittance_cents: int
    goodwill_deduction_cents: int
    net_remittance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict, total=False):
    id: str
    customer_id: str
    booking_id: Optional[str]
    reason_code: str
    score_delta: int
    status: str
    created_at: str
    updated_at: str
    version: int
