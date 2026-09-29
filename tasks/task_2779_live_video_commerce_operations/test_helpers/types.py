"""Domain types: status enums, role enum and entity TypedDicts.

All thirteen resources carry the four common properties the PRD declares:
id, created_at, updated_at and version.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOW_PRODUCER = "ShowProducer"
    MERCHANDISING_MANAGER = "MerchandisingManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MODERATOR = "Moderator"
    HOST = "Host"
    VIEWER = "Viewer"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class ClaimSubstantiationStatus(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    SUBSTANTIATED = "SUBSTANTIATED"
    REJECTED = "REJECTED"


class ChatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MUTED = "MUTED"


class ShowStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    LIVE = "LIVE"
    ENDED = "ENDED"
    SETTLED = "SETTLED"


class StreamChannelStatus(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONED = "PROVISIONED"
    LIVE = "LIVE"
    FAILED = "FAILED"
    ENDED = "ENDED"


class StreamPlatform(str, Enum):
    FLAGSHIP_APP = "FLAGSHIP_APP"
    SOCIAL_A = "SOCIAL_A"
    SOCIAL_B = "SOCIAL_B"
    PARTNER_APP = "PARTNER_APP"


class HostBookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BookingRole(str, Enum):
    PRIMARY = "PRIMARY"
    GUEST = "GUEST"


class ReplayMarkerStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class FlashOfferStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class DisclosureRecordStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    VOIDED = "VOIDED"


class DisclosureType(str, Enum):
    PAID_ENDORSEMENT = "PAID_ENDORSEMENT"
    MATERIAL_CONNECTION = "MATERIAL_CONNECTION"
    FREE_PRODUCT = "FREE_PRODUCT"


class CartStatus(str, Enum):
    OPEN = "OPEN"
    ABANDONED = "ABANDONED"
    CHECKED_OUT = "CHECKED_OUT"
    EXPIRED = "EXPIRED"


class CartItemState(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ReleasedReason(str, Enum):
    OFFER_EXPIRED = "OFFER_EXPIRED"
    OFFER_CANCELLED = "OFFER_CANCELLED"
    CART_ABANDONED = "CART_ABANDONED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class PaymentState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class FulfillmentState(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"


class InteractionKind(str, Enum):
    CHAT = "CHAT"
    QUESTION = "QUESTION"
    POLL = "POLL"


class InteractionState(str, Enum):
    PENDING_MODERATION = "PENDING_MODERATION"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    QUEUED = "QUEUED"
    ROUTED = "ROUTED"
    ANSWERED = "ANSWERED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MarginVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class HostScoreVariant(str, Enum):
    LIVE_WINDOW = "LIVE_WINDOW"
    ATTRIBUTED_72H = "ATTRIBUTED_72H"


class Host(TypedDict):
    id: str
    full_name: str
    handle: str
    commission_pct: float
    certification_status: str
    disclosure_certification_expires_at: Optional[str]
    effectiveness_score_live: int
    effectiveness_score_attributed: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    title: str
    base_price_cents: int
    unit_cost_cents: int
    on_hand_qty: int
    reserved_qty: int
    committed_qty: int
    available_qty: int
    claim_text: Optional[str]
    claim_substantiation_status: str
    substantiated_by_user_id: Optional[str]
    substantiated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Viewer(TypedDict):
    id: str
    display_name: str
    email: str
    chat_status: str
    strike_count: int
    muted_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict):
    id: str
    title: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    created_by_user_id: str
    readiness_checked_at: Optional[str]
    went_live_at: Optional[str]
    ended_at: Optional[str]
    settled_at: Optional[str]
    compliance_signoff_by_user_id: Optional[str]
    attestation_note: Optional[str]
    simulcast_readiness_index: int
    gross_merchandise_cents: int
    margin_provisional_cents: Optional[int]
    margin_final_cents: Optional[int]
    abandoned_cart_count: int
    abandonment_rate_bp: int
    pending_question_count: int
    replay_attributed_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class StreamChannel(TypedDict):
    id: str
    show_id: str
    platform: str
    target_latency_ms: int
    is_primary: bool
    status: str
    latency_ms: Optional[int]
    dropped_frame_pct: float
    readiness_index: int
    health_report_count: int
    created_at: str
    updated_at: str
    version: int


class HostBooking(TypedDict):
    id: str
    show_id: str
    host_id: str
    role: str
    call_time_at: str
    release_time_at: str
    fee_cents: int
    status: str
    confirmed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineupSlot(TypedDict):
    id: str
    show_id: str
    product_id: str
    slot_sequence: int
    planned_start_at: str
    planned_end_at: str
    planned_qty: int
    unit_cost_snapshot_cents: int
    replay_marker_status: str
    replay_marker_offset_sec: Optional[int]
    replay_product_link_url: Optional[str]
    replay_attributed_revenue_cents: int
    replay_conversions_count: int
    created_at: str
    updated_at: str
    version: int


class FlashOffer(TypedDict):
    id: str
    lineup_slot_id: str
    offer_price_cents: int
    window_start_at: str
    window_end_at: str
    max_qty: int
    held_qty: int
    sold_qty: int
    remaining_qty: int
    status: str
    activated_at: Optional[str]
    superseded_by_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureRecord(TypedDict):
    id: str
    show_id: str
    host_booking_id: str
    disclosure_type: str
    required_script_code: str
    script_code_spoken: Optional[str]
    status: str
    acknowledged_at: Optional[str]
    acknowledged_late: bool
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    show_id: str
    viewer_id: str
    status: str
    held_item_count: int
    pre_discount_subtotal_cents: int
    bundle_discount_pct: float
    recovered_count: int
    abandoned_at: Optional[str]
    recovery_deadline_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CartItem(TypedDict):
    id: str
    cart_id: str
    flash_offer_id: str
    lineup_slot_id: str
    qty: int
    list_unit_price_cents: int
    offer_unit_price_cents: int
    effective_unit_price_cents: int
    line_gross_cents: int
    line_tax_cents: int
    state: str
    released_reason: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    cart_id: str
    show_id: str
    viewer_id: str
    merchandise_cents: int
    tax_cents: int
    shipping_cents: int
    total_cents: int
    payment_state: str
    fulfillment_state: str
    host_commission_accrued_cents: int
    refunded_cents: int
    captured_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interaction(TypedDict):
    id: str
    show_id: str
    viewer_id: Optional[str]
    host_id: Optional[str]
    kind: str
    state: str
    body: str
    options: Optional[List[str]]
    tallies: Optional[Dict[str, int]]
    voted_viewer_ids: Optional[List[str]]
    vote_count: int
    defer_count: int
    answer_body: Optional[str]
    blocked_reason: Optional[str]
    moderated_at: Optional[str]
    routed_at: Optional[str]
    answered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
