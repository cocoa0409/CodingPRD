"""Domain types: status enums, role enum and entity TypedDicts.

Every resource in this domain carries the full common property set
(``id``, ``created_at``, ``updated_at``, ``version``); no resource omits
``updated_at`` or ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role model
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PATRON = "Patron"
    OPS_MANAGER = "OpsManager"
    ALLOCATIONS_COORDINATOR = "AllocationsCoordinator"
    CUSTOMER_SERVICE = "CustomerService"
    FINANCIAL_OPS = "FinancialOps"
    CONCIERGE_DESK_STAFF = "ConciergeDeskStaff"
    PRODUCER_ANALYST = "ProducerAnalyst"
    DEMAND_ANALYST = "DemandAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ONSALE = "ONSALE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RushAllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TicketType(str, Enum):
    RUSH = "RUSH"
    RUSH_PREMIUM = "RUSH_PREMIUM"
    DRAW = "DRAW"
    STANDARD = "STANDARD"


class ReconciliationStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    RECONCILED = "RECONCILED"
    MISMATCH = "MISMATCH"


class DrawEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    WINNER = "WINNER"
    WAITLISTED = "WAITLISTED"
    LOSER = "LOSER"
    PURCHASED = "PURCHASED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    VOIDED = "VOIDED"


class LogisticsStatus(str, Enum):
    AWAITING_HANDOFF = "AWAITING_HANDOFF"
    DELIVERED = "DELIVERED"
    COLLECTED = "COLLECTED"
    REVOKED = "REVOKED"


class HandoffStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_CONCIERGE = "PENDING_CONCIERGE"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class QueuePositionStatus(str, Enum):
    WAITING = "WAITING"
    ADMITTED = "ADMITTED"
    PURCHASED = "PURCHASED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"


class SeatHoldStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    ORPHANED = "ORPHANED"
    EXPIRED = "EXPIRED"


class HoldKind(str, Enum):
    BOX_OFFICE = "BOX_OFFICE"
    HOUSE = "HOUSE"
    COMP = "COMP"
    ALLOCATION = "ALLOCATION"


class RefundRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    COMPENSATED = "COMPENSATED"


class RefundReasonCode(str, Enum):
    PATRON_REQUEST = "PATRON_REQUEST"
    PERFORMANCE_CANCELLED = "PERFORMANCE_CANCELLED"
    PLATFORM_FAULT = "PLATFORM_FAULT"
    DESK_FAILURE = "DESK_FAILURE"


class ExchangeRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    COMPENSATED = "COMPENSATED"


class ConciergeDeskStatus(str, Enum):
    OPEN = "OPEN"
    SATURATED = "SATURATED"
    CLOSED = "CLOSED"


class HandoffModel(str, Enum):
    MOBILE_PUSH = "MOBILE_PUSH"
    CONCIERGE_DESK = "CONCIERGE_DESK"
    HYBRID = "HYBRID"


class PatronStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id + created_at + updated_at + version)
# --------------------------------------------------------------------------

class Production(TypedDict):
    id: str
    title: str
    producer_org: str
    status: str
    refund_window_hours: int
    exchange_fee_cents: int
    exchange_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict):
    id: str
    market_code: str
    city: str
    handoff_model: str
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict):
    id: str
    production_id: str
    market_code: str
    venue_name: str
    starts_at: str
    face_value_cents: int
    total_seat_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RushAllocation(TypedDict):
    id: str
    performance_id: str
    ticket_type: str
    daily_quantity: int
    discount_pct: float
    release_time_local: str
    refundable: bool
    per_order_limit: int
    claim_window_minutes: Optional[int]
    winner_basis_points: Optional[int]
    waitlist_multiplier: Optional[int]
    quantity_released_today: int
    quantity_sold_today: int
    quantity_carried_forward: int
    daily_release_cap: int
    status: str
    qa_checked_by: Optional[str]
    released_by: Optional[str]
    reconcile_deadline_at: Optional[str]
    reconciliation_status: str
    reconciliation_variance_count: int
    reconciliation_variance_seats: List[str]
    created_at: str
    updated_at: str
    version: int


class DrawEntry(TypedDict):
    id: str
    performance_id: str
    allocation_id: str
    patron_id: str
    status: str
    entered_at: str
    rank_position: Optional[int]
    notified_at: Optional[str]
    claim_deadline_at: Optional[str]
    purchase_id: Optional[str]
    reinstatement_count: int
    created_at: str
    updated_at: str
    version: int


class TicketPurchase(TypedDict):
    id: str
    performance_id: str
    allocation_id: str
    patron_id: str
    quantity: int
    idempotency_key: str
    unit_price_cents: int
    surge_multiplier_bp: int
    subtotal_cents: int
    quoted_total_cents: Optional[int]
    payment_status: str
    logistics_status: str
    handoff_status: str
    handoff_token: Optional[str]
    handoff_verified_at: Optional[str]
    handoff_failed_at: Optional[str]
    seat_labels: List[str]
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class SeatHold(TypedDict):
    id: str
    performance_id: str
    allocation_id: Optional[str]
    seat_label: str
    hold_kind: str
    origin_ref: Optional[str]
    status: str
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QueuePosition(TypedDict):
    id: str
    performance_id: str
    patron_id: str
    status: str
    joined_at: str
    admit_at: Optional[str]
    admit_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConciergeDesk(TypedDict):
    id: str
    market_code: str
    desk_code: str
    daily_capacity: int
    handoffs_today: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    purchase_id: str
    patron_id: str
    reason_code: str
    status: str
    approved_by: Optional[str]
    requested_by: Optional[str]
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ExchangeRequest(TypedDict):
    id: str
    purchase_id: str
    patron_id: str
    original_amount_cents: int
    target_allocation_id: str
    status: str
    fee_cents: Optional[int]
    value_returned_cents: Optional[int]
    approved_by: Optional[str]
    requested_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    email: str
    display_name: str
    market_code: str
    draw_violation_count: float
    status: str
    created_at: str
    updated_at: str
    version: int