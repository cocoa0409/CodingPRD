"""Serialized shapes of every entity and read model in the contract.

These are documentation-grade typed dictionaries: each one lists exactly the
fields the contract says appear in that entity's serialized form, in the order
the contract lists them. Tests use them to keep field names honest and to make
the expected shape of a response reviewable in one place.

Twelve entities plus the reservation carry the four common fields (``id``,
``created_at``, ``updated_at``, ``version``). The freeze window is the one
create-only entity: it carries ``id`` and ``created_at`` only.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ── Envelope ───────────────────────────────────────────────────────────────


class ResponseMeta(TypedDict, total=False):
    """The meta block every response carries; list reads add the page fields."""

    api_request_id: str
    timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorBody(TypedDict, total=False):
    error_id: str
    message: str
    details: Dict[str, Any]


class ApiEnvelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any
    error: ErrorBody


# ── Core registry ──────────────────────────────────────────────────────────


class Property(TypedDict):
    id: str
    code: str
    name: str
    currency_code: str
    overbooking_pct_bp: int
    booking_horizon_days: int
    mix_window_days: int
    rate_mismatch_tolerance_cents: int
    required_image_count: int
    created_at: str
    updated_at: str
    version: int


class RoomType(TypedDict):
    id: str
    property_id: str
    code: str
    name: str
    physical_capacity_units: int
    master_description_hash: str
    master_image_count: int
    overbooking_pct_bp: Optional[int]
    effective_overbooking_pct_bp: int
    created_at: str
    updated_at: str
    version: int


class InventoryDay(TypedDict):
    id: str
    room_type_id: str
    stay_date: str
    physical_capacity_units: int
    overbooking_ceiling_units: int
    allocated_units: int
    committed_units: int
    shared_pool_units: int
    pooled_state: str
    created_at: str
    updated_at: str
    version: int


# ── Channels and connectivity ──────────────────────────────────────────────


class Channel(TypedDict):
    id: str
    property_id: str
    code: str
    channel_kind: str
    commission_bp: int
    sell_adjustment_bp: int
    allows_member_rate: bool
    allows_opaque_rate: bool
    geo_market_codes: List[str]
    requires_content_parity: bool
    gross_revenue_cents: int
    commission_accrued_cents: int
    net_revenue_cents: int
    room_nights_sold: int
    bookings_count: int
    cancellations_count: int
    mismatch_alert_count: int
    created_at: str
    updated_at: str
    version: int


class ChannelConnection(TypedDict):
    id: str
    channel_id: str
    protocol: str
    endpoint_url: str
    heartbeat_interval_minutes: int
    connection_state: str
    consecutive_failures: int
    last_heartbeat_at: Optional[str]
    last_failure_code: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConnectivityFreezeWindow(TypedDict):
    """The one create-only entity: no ``updated_at`` and no ``version``."""

    id: str
    connection_id: str
    starts_at: str
    ends_at: str
    effective_starts_at: str
    reason: str
    created_at: str


# ── Rate plans, mappings and promotions ────────────────────────────────────


class RatePlan(TypedDict):
    id: str
    property_id: str
    code: str
    rate_class: str
    parent_rate_plan_id: Optional[str]
    base_amount_cents: Optional[int]
    offset_kind: str
    offset_bp: Optional[int]
    offset_amount_cents: Optional[int]
    floor_amount_cents: int
    ceiling_amount_cents: int
    package_inclusion_cents: int
    member_only: bool
    negotiated_account_code: Optional[str]
    plan_state: str
    derivation_depth: int
    resolved_base_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ChannelMapping(TypedDict):
    id: str
    rate_plan_id: str
    channel_id: str
    room_type_id: str
    external_rate_code: str
    mapping_state: str
    content_description_hash: Optional[str]
    content_image_count: Optional[int]
    parity_state: str
    last_pushed_rate_cents: Optional[int]
    last_push_at: Optional[str]
    observed_rate_cents: Optional[int]
    observed_stay_date: Optional[str]
    mismatch_delta_cents: Optional[int]
    mismatch_state: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    rate_plan_id: str
    code: str
    promo_kind: str
    discount_kind: str
    discount_bp: Optional[int]
    discount_amount_cents: Optional[int]
    geo_market_codes: List[str]
    start_date: str
    end_date: str
    approval_status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    reject_reason: Optional[str]
    revision_count: int
    distribution_status: str
    created_at: str
    updated_at: str
    version: int


# ── Restrictions and allotments ────────────────────────────────────────────


class Restriction(TypedDict):
    id: str
    room_type_id: str
    rate_plan_id: Optional[str]
    restriction_type: str
    start_date: str
    end_date: str
    value_nights: Optional[int]
    origin: str
    restriction_state: str
    lifted_at: Optional[str]
    lift_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelAllocation(TypedDict):
    id: str
    room_type_id: str
    channel_id: str
    allocated_units: int
    start_date: str
    end_date: str
    consumed_units: int
    allocation_state: str
    superseded_at: Optional[str]
    recalled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Reservations ───────────────────────────────────────────────────────────


class NightlyBreakdownEntry(TypedDict):
    """One night of a reservation's stored charge breakdown."""

    stay_date: str
    sell_rate_cents: int
    commissionable_cents: int
    commission_cents: int


class Reservation(TypedDict):
    id: str
    property_id: str
    channel_id: str
    rate_plan_id: str
    room_type_id: str
    arrival_date: str
    nights: int
    departure_date: str
    member_flag: bool
    geo_market_code: Optional[str]
    negotiated_account_code: Optional[str]
    override_overbooking: bool
    reservation_state: str
    nightly_breakdown: List[NightlyBreakdownEntry]
    gross_amount_cents: int
    commission_amount_cents: int
    net_amount_cents: int
    loyalty_credit_cents: int
    overbooking_overridden: bool
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Distribution ───────────────────────────────────────────────────────────


class DistributionBatch(TypedDict):
    id: str
    property_id: str
    payload_kind: str
    source_ref_kind: str
    source_ref_id: str
    batch_state: str
    total_jobs: int
    applied_jobs: int
    rejected_jobs: int
    abandoned_jobs: int
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateDistributionJob(TypedDict):
    id: str
    batch_id: str
    channel_mapping_id: str
    sequence_index: int
    payload_kind: str
    payload_rate_cents: Optional[int]
    job_state: str
    attempt_count: int
    failure_reason: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Computed read models ───────────────────────────────────────────────────


class QuotedRate(TypedDict):
    """The six-step sell-rate resolution exposed for one mapping and one date."""

    channel_mapping_id: str
    stay_date: str
    base_amount_cents: int
    promotion_discount_cents: int
    discount_cap_cents: int
    channel_adjusted_cents: int
    clamped_cents: int
    sell_amount_cents: int
    applied_promotion_codes: List[str]


class ChannelPerformance(TypedDict):
    channel_id: str
    basis: str
    window_start_date: str
    window_end_date: str
    gross_amount_cents: int
    commission_amount_cents: int
    net_amount_cents: int
    room_nights: int
    net_adr_cents: Optional[int]
    commission_cost_ratio_bp: Optional[int]
    health_score_bp: Optional[int]


class BookingPace(TypedDict):
    room_type_id: str
    target_stay_date: str
    baseline: str
    as_of_date: str
    days_out: int
    target_room_nights: int
    baseline_room_nights: int
    pace_index_bp: Optional[int]
    pace_state: str


class RankedChannel(TypedDict):
    """One entry of the channel-mix ranking; it carries no channel identifier."""

    rank: int
    net_adr_cents: Optional[int]
    commission_bp: int
    commission_cost_ratio_bp: Optional[int]
    room_nights: int


class ChannelMix(TypedDict):
    property_id: str
    window_start_date: str
    window_end_date: str
    ranked_channels: List[RankedChannel]


class ClockEcho(TypedDict):
    current_utc: str
