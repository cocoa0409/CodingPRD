"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD section 2.4: primary resources carry id, created_at,
updated_at and version; the tracking event is append-only and carries only
id and created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MERCHANT = "Merchant"
    COURIER = "Courier"
    SUPPORT_AGENT = "SupportAgent"


class MerchantStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PricingPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OverrideEffect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class FulfillmentStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    UNDELIVERABLE = "UNDELIVERABLE"
    RETURN_IN_PROGRESS = "RETURN_IN_PROGRESS"
    RETURNED_TO_STORE = "RETURNED_TO_STORE"
    DISPOSAL_PENDING = "DISPOSAL_PENDING"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class CourierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BatchStatus(str, Enum):
    COURIER_ASSIGNED = "COURIER_ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TrackingEventType(str, Enum):
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    COURIER_ASSIGNED = "COURIER_ASSIGNED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    UNDELIVERABLE = "UNDELIVERABLE"
    RETURN_IN_PROGRESS = "RETURN_IN_PROGRESS"
    RETURNED_TO_STORE = "RETURNED_TO_STORE"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"
    NOTE = "NOTE"


class TrackingVisibility(str, Enum):
    MERCHANT_VISIBLE = "MERCHANT_VISIBLE"
    INTERNAL_ONLY = "INTERNAL_ONLY"


class DispositionResolution(str, Enum):
    RETURN_TO_STORE = "RETURN_TO_STORE"
    DISPOSE = "DISPOSE"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class UndeliverableReason(str, Enum):
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    ADDRESS_ISSUE = "ADDRESS_ISSUE"
    DAMAGED_IN_TRANSIT = "DAMAGED_IN_TRANSIT"


class FaultCode(str, Enum):
    COURIER_DELAY = "COURIER_DELAY"
    PLATFORM_OUTAGE = "PLATFORM_OUTAGE"
    MERCHANT_FULFILLMENT = "MERCHANT_FULFILLMENT"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    ADDRESS_ISSUE = "ADDRESS_ISSUE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class SlaReportStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ServiceCreditStatus(str, Enum):
    ACCRUED = "ACCRUED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Merchant(TypedDict, total=False):
    id: str
    name: str
    status: str
    billing_balance_cents: int
    credit_balance_cents: int
    default_refund_split_merchant_pct: int
    late_credit_enabled: bool
    created_at: str
    updated_at: str
    version: int


class MerchantStore(TypedDict, total=False):
    id: str
    merchant_id: str
    name: str
    address_text: str
    lat: float
    lng: float
    delivery_radius_m: int
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistanceBand(TypedDict):
    max_m: int
    base_cents: int
    per_100m_cents: int


class ValueTier(TypedDict):
    min_order_value_cents: int
    surcharge_cents: int


class PeakWindow(TypedDict):
    start_local_hhmm: str
    end_local_hhmm: str


class PricingPolicy(TypedDict, total=False):
    id: str
    merchant_id: str
    distance_bands: List[DistanceBand]
    value_tiers: List[ValueTier]
    peak_windows: List[PeakWindow]
    peak_uplift_pct: float
    surge_passthrough_pct: float
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceabilityOverride(TypedDict, total=False):
    id: str
    store_id: str
    address_pattern: str
    effect: str
    created_at: str
    updated_at: str
    version: int


class ServiceabilityVerdict(TypedDict, total=False):
    serviceable: bool
    distance_m: int
    matched_override_effect: Optional[str]


class DeliveryQuote(TypedDict, total=False):
    id: str
    merchant_id: str
    store_id: str
    dropoff_lat: float
    dropoff_lng: float
    address_text: str
    order_value_cents: int
    pickup_ready_at: str
    distance_m: int
    band_fee_cents: int
    value_surcharge_cents: int
    peak_uplift_cents: int
    surge_component_cents: int
    quoted_fee_cents: int
    pricing_policy_id: str
    quoted_surge_multiplier: float
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict, total=False):
    id: str
    quote_id: str
    merchant_id: str
    store_id: str
    batch_id: Optional[str]
    customer_reference: str
    idempotency_key: str
    promised_at: Optional[str]
    fulfillment_status: str
    billing_status: str
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    merchant_invoice_cents: Optional[int]
    batch_fee_share_cents: Optional[int]
    late_credit_cents: int
    delivered_at: Optional[str]
    undeliverable_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Courier(TypedDict, total=False):
    id: str
    name: str
    status: str
    max_active_deliveries: int
    created_at: str
    updated_at: str
    version: int


class DeliveryBatch(TypedDict, total=False):
    id: str
    store_id: str
    courier_id: str
    order_ids: List[str]
    dispatch_window_start: str
    dispatch_window_end: str
    courier_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackingEvent(TypedDict, total=False):
    # Append-only feed item: id + created_at only (no updated_at, no version).
    id: str
    delivery_order_id: str
    event_type: str
    note: str
    visibility: str
    occurred_at: str
    created_at: str


class Disposition(TypedDict, total=False):
    id: str
    delivery_order_id: str
    resolution: str
    return_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict, total=False):
    id: str
    delivery_order_id: str
    merchant_id: str
    fault_code: str
    claimed_amount_cents: int
    merchant_share_cents: Optional[int]
    platform_share_cents: Optional[int]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SlaReport(TypedDict, total=False):
    id: str
    merchant_id: str
    period_start: str
    period_end: str
    total_deliveries: Optional[int]
    late_deliveries_gross: Optional[int]
    attainment_rate_gross: Optional[float]
    attainment_rate_fault_adjusted: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict, total=False):
    id: str
    merchant_id: str
    sla_report_id: str
    delivery_order_id: str
    amount_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
