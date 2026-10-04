"""Domain types: entity TypedDicts, status enums, and the role enum.

The primary resources carry the standard system-managed field set (`id`,
`created_at`, `updated_at`, `version`). Payment is the single exception: it is
an immutable ledger entry and carries only `id` and `created_at`.
"""

from enum import Enum
from typing import TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    RISK_ANALYST = "RiskAnalyst"
    RETAILER = "Retailer"
    BRAND = "Brand"


class StoreType(str, Enum):
    BRICK_AND_MORTAR = "BRICK_AND_MORTAR"
    ONLINE = "ONLINE"
    HYBRID = "HYBRID"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OnboardingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class Attribution(str, Enum):
    MARKETPLACE = "MARKETPLACE"
    BRAND_REFERRED = "BRAND_REFERRED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class ReturnAuthStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class FlagType(str, Enum):
    STRAW_STOREFRONT = "STRAW_STOREFRONT"
    CONSUMER_RESELLER = "CONSUMER_RESELLER"
    RETURN_ABUSE = "RETURN_ABUSE"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class Retailer(TypedDict):
    id: str
    legal_name: str
    store_type: str
    address: str
    lat: float
    lng: float
    storefront_proof_url: str
    resale_certificate_no: str
    storefront_proof_status: str
    resale_cert_status: str
    verification_status: str
    verification_resubmission_count: int
    risk_tier: str
    return_rate: float
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    name: str
    contact_email: str
    onboarding_status: str
    min_order_value_cents: int
    default_case_pack_size: int
    lead_time_days: int
    payout_delay_days: int
    referral_code: str
    payout_balance_cents: int
    abuse_flags: int
    created_at: str
    updated_at: str
    version: int


class CreditAccount(TypedDict):
    id: str
    retailer_id: str
    limit_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    retailer_id: str
    brand_id: str
    attribution: str
    order_seq: int
    subtotal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku: str
    unit_price_cents: int
    qty: int
    amount_cents: int
    net_sold_qty: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    order_id: str
    amount_due_cents: int
    due_date: str
    paid_amount_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    # Immutable ledger entry: only id + created_at plus its own fields.
    id: str
    invoice_id: str
    amount_cents: int
    paid_at: str
    created_at: str


class ReturnAuthorization(TypedDict):
    id: str
    order_id: str
    is_opening_order: bool
    return_fee_cents: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict):
    id: str
    return_auth_id: str
    order_line_id: str
    qty: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    brand_id: str
    order_id: str
    gross_cents: int
    commission_bps: int
    commission_cents: int
    net_cents: int
    scheduled_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusivityGrant(TypedDict):
    id: str
    brand_id: str
    retailer_id: str
    center_lat: float
    center_lng: float
    radius_km: float
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict):
    id: str
    retailer_id: str
    order_id: str
    flag_type: str
    status: str
    created_at: str
    updated_at: str
    version: int
