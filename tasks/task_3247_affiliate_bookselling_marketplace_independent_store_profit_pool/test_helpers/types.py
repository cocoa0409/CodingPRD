"""Domain types: entity shapes, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_MANAGER = "StoreManager"
    PARTNER = "Partner"
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE = "CustomerService"
    WHOLESALER_OPS = "WholesalerOps"
    FINANCE_OPS = "FinanceOps"


class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookFormat(str, Enum):
    PRINT = "PRINT"
    EBOOK = "EBOOK"
    AUDIOBOOK = "AUDIOBOOK"


class BookStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class StoreStatus(str, Enum):
    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class PartnerKind(str, Enum):
    AUTHOR = "AUTHOR"
    PUBLICATION = "PUBLICATION"
    INFLUENCER = "INFLUENCER"


class PartnerStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ListStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    SENT_TO_WHOLESALER = "SENT_TO_WHOLESALER"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"


class ReasonCode(str, Enum):
    DAMAGED = "DAMAGED"
    WRONG_ITEM = "WRONG_ITEM"
    UNWANTED = "UNWANTED"


class LedgerKind(str, Enum):
    ORDER_ACCRUAL = "ORDER_ACCRUAL"
    COMMISSION_REVERSAL = "COMMISSION_REVERSAL"
    RETURN_CLAWBACK = "RETURN_CLAWBACK"
    POOL_DISTRIBUTION = "POOL_DISTRIBUTION"
    ADJUSTMENT = "ADJUSTMENT"


class PoolStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    DISTRIBUTED = "DISTRIBUTED"
    VOID = "VOID"


class ShareMode(str, Enum):
    EQUAL_SPLIT = "EQUAL_SPLIT"
    SALES_WEIGHTED = "SALES_WEIGHTED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class IssueKind(str, Enum):
    LATE_SHIPMENT = "LATE_SHIPMENT"
    DAMAGED_ITEM = "DAMAGED_ITEM"
    WRONG_ITEM = "WRONG_ITEM"
    BILLING = "BILLING"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class Publisher(TypedDict, total=False):
    id: str
    name: str
    discount_pct: float
    returns_allowed: bool
    return_window_days: int
    return_credit_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Book(TypedDict, total=False):
    id: str
    publisher_id: str
    isbn: str
    title: str
    format: str
    list_price_cents: int
    ebook_partner_rev_share_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class AffiliateStore(TypedDict, total=False):
    id: str
    shop_name: str
    slug: str
    commission_pct: float
    pool_opt_in: bool
    payout_threshold_cents: int
    status: str
    activated_at: Optional[str]
    suspended_at: Optional[str]
    accrued_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AffiliatePartner(TypedDict, total=False):
    id: str
    display_name: str
    partner_kind: str
    commission_pct: float
    payout_threshold_cents: int
    status: str
    accrued_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class BookList(TypedDict, total=False):
    id: str
    owner_store_id: str
    title: str
    items: List[dict]
    status: str
    publish_count: int
    created_at: str
    updated_at: str
    version: int


class PricedLine(TypedDict, total=False):
    book_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    wholesale_unit_cents: int
    returned_quantity: int


class BookOrder(TypedDict, total=False):
    id: str
    customer_id: str
    home_store_id: Optional[str]
    attributed_store_id: Optional[str]
    attributed_partner_id: Optional[str]
    source_list_id: Optional[str]
    lines: List[dict]
    priced_lines: List[PricedLine]
    payment_status: str
    fulfillment_status: str
    gross_cents: int
    wholesale_cost_cents: int
    platform_margin_cents: int
    commission_cents: int
    refunded_cents: int
    retained_cents: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    order_id: str
    line_index: int
    quantity: int
    reason_code: str
    status: str
    refund_cents: int
    wholesale_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionLedgerEntry(TypedDict, total=False):
    # Append-only ledger: carries ONLY id + created_at (no updated_at, no version).
    id: str
    affiliate_store_id: Optional[str]
    affiliate_partner_id: Optional[str]
    order_id: Optional[str]
    pool_distribution_id: Optional[str]
    kind: str
    amount_cents: int
    reversed: bool
    created_at: str


class ShareLine(TypedDict, total=False):
    store_id: str
    eligible: bool
    share_cents: int


class ProfitPoolDistribution(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    pool_cents: int
    share_mode: str
    status: str
    eligible_store_count: int
    remainder_cents: int
    share_lines: List[ShareLine]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    affiliate_store_id: Optional[str]
    affiliate_partner_id: Optional[str]
    amount_cents: int
    status: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    order_id: str
    opened_by_customer_id: str
    issue_kind: str
    status: str
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    book_isbn: str
    discount_pct: float
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
