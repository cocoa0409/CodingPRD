"""Domain types: status enums, role enum, and entity TypedDicts.

Every entity in this API carries the four system-managed properties described in
the PRD (id, created_at, updated_at, version); there are no append-only entities
that omit the latter two.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class RoutePosture(str, Enum):
    ACTIVE = "ACTIVE"
    SURGE = "SURGE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class TravelStatus(str, Enum):
    PLANNED = "PLANNED"
    WATCHING = "WATCHING"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class WatchNotificationStatus(str, Enum):
    ARMED = "ARMED"
    NOTIFIED = "NOTIFIED"
    WAIT = "WAIT"
    BUY_NOW = "BUY_NOW"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


class FreezeStatus(str, Enum):
    DRAFT = "DRAFT"
    HELD = "HELD"
    FROZEN = "FROZEN"
    CLAIM_PENDING = "CLAIM_PENDING"
    CLAIMED = "CLAIMED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ProtectionQuotedStatus(str, Enum):
    QUOTED = "QUOTED"
    QUOTED_FROZEN = "QUOTED_FROZEN"
    QUOTED_ACTIVE = "QUOTED_ACTIVE"
    QUOTED_FROZEN_ON_UNPUBLISHED_CURVE = "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE"


class ProtectionLifecycleStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    CHANGE_IN_PROGRESS = "CHANGE_IN_PROGRESS"
    CANCELLED_PROTECTED = "CANCELLED_PROTECTED"
    REBOOKED = "REBOOKED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SETTLED_WITH_PURCHASE = "SETTLED_WITH_PURCHASE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ChangeEventStatus(str, Enum):
    OPEN = "OPEN"
    OPTION_SELECTED = "OPTION_SELECTED"
    HELD = "HELD"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RebookingOptionStatus(str, Enum):
    OFFERED = "OFFERED"
    SELECTED = "SELECTED"
    HELD = "HELD"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"
    RETIRED = "RETIRED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    MEMBERSHIP_1 = "MEMBERSHIP_1"
    MEMBERSHIP_2 = "MEMBERSHIP_2"
    PREMIUM = "PREMIUM"
    CHANGE_FEE = "CHANGE_FEE"
    HEDGE_TOPUP = "HEDGE_TOPUP"


class HedgingPositionStatus(str, Enum):
    OPEN = "OPEN"
    HEDGED = "HEDGED"
    SETTLED = "SETTLED"
    LAPSED = "LAPSED"


class RiskPoolStatus(str, Enum):
    OPEN = "OPEN"
    ABSORBING = "ABSORBING"
    BOUND = "BOUND"


class DestinationOptionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOUND = "BOUND"
    TAKEN = "TAKEN"


class DepositIntegrityFlag(str, Enum):
    INTEGRITY_CONSISTENT = "INTEGRITY_CONSISTENT"
    INTEGRITY_UNDER_RECOGNIZED = "INTEGRITY_UNDER_RECOGNIZED"
    INTEGRITY_OVER_RECOGNIZED = "INTEGRITY_OVER_RECOGNIZED"


class UserRole(str, Enum):
    TRAVELER = "Traveler"
    OPS_AGENT = "OpsAgent"
    RISK_ANALYST = "RiskAnalyst"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_ADMIN = "PlatformAdmin"
    SYSTEM_OPERATOR = "SystemOperator"


class InsuranceTier(int, Enum):
    TIER_1 = 30000
    TIER_2 = 50000
    TIER_3 = 100000
    TIER_4 = 200000
    TIER_5 = 300000


# A syntactically valid UUID that is never allocated by the server.
MISMATCHED_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────

class Route(TypedDict, total=False):
    id: str
    origin_airport: str
    destination_airport: str
    flight_number: str
    travel_class: str
    region: str
    base_fare_cents: int
    fare_band_cents: List[int]
    peak_price_day_index: int
    seats_left: int
    volatility_index: float
    hedge_ratio_pct: float
    max_guarantee_exposure_cents: int
    default_disruption_probability: float
    disruption_severity_index: float
    protection_base_rate: float
    protection_floor_rate: float
    cancel_minimum_disruption: float
    disclosure_version: int
    peak_day_demand_multiplier: float
    disclosure_headline: str
    war_chest_cents: int
    reserved_exposure_cents: int
    available_exposure_cents: int
    pooled_exposure_cents: int
    posture: str
    posture_reason_code: str
    open_freeze_count: int
    curve_published: bool
    highest_curve_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Itinerary(TypedDict, total=False):
    id: str
    route_id: str
    departure_date: str
    traveler_user_id: str
    booking_date: str
    listed_fare_cents: int
    last_observed_fare_cents: int
    demand_curve_price_cents: int
    each_day_disruption_fare_cents: int
    fare_tier_ceiling_cents: int
    observed_fares_cents: List[int]
    travel_status: str
    watch_armed: bool
    guarantee_locked: bool
    booking_hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceObservation(TypedDict, total=False):
    id: str
    route_id: str
    itinerary_id: str
    fare_cents: int
    seats_left: int
    observed_at: str
    created_at: str
    updated_at: str
    version: int


class DemandCurve(TypedDict, total=False):
    id: str
    route_id: str
    price_date: str
    each_day_prices_cents: List[int]
    seats_left_at_each_day: List[int]
    published_at: str
    created_at: str
    updated_at: str
    version: int


class WatchSubscription(TypedDict, total=False):
    id: str
    itinerary_id: str
    armed_at: str
    expires_at: str
    notification_status: str
    notification_attempt_count: int
    last_notified_fare_cents: int
    last_notified_at: Optional[str]
    cooldown_until: Optional[str]
    cooldown_suppressed: bool
    buy_now_warranty_applied: bool
    locked_fare_cents: int
    created_at: str
    updated_at: str
    version: int


class PriceFreeze(TypedDict, total=False):
    id: str
    itinerary_id: str
    manifest_fare_cents: int
    migrated_manifest: bool
    cap_cents: int
    deposit_cents: int
    freeze_date: Optional[str]
    freeze_expires_at: Optional[str]
    firm_tier_ceiling_cents: int
    cap_tier_ceiling_cents: int
    guaranteed_ceiling_cents: int
    overshoot_cents: int
    capped_impact_cents: int
    exposure_cents: int
    guaranteed_ceiling_test_cents: int
    hedged_exposure_cents: int
    unhedged_exposure_cents: int
    deposit_attributed_cents: int
    membership_days_elapsed: int
    pattern_day_count: int
    custody_held_cents: int
    custody_return_pending_cents: int
    deposit_forfeited_cents: int
    frozen_effective_at: Optional[str]
    deposit_integrity_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionProduct(TypedDict, total=False):
    id: str
    itinerary_id: str
    freeze_id: Optional[str]
    product_type: str
    quoted_status: str
    lifecycle_status: str
    cancellation_disruption_probability: float
    disruption_probability: float
    change_disruption_probability: float
    change_minimum_applied: bool
    quote_probable_loss_cents: int
    minimum_disruption_met: bool
    bonus_days_total: int
    bonus_days_remaining: int
    premium_cents: int
    cancelled_by_member: bool
    redeemed_value_cents: int
    duration_consumed_days: int
    terminated_hard: bool
    coverage_expires_at: str
    suspended_under_cap: bool
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict, total=False):
    id: str
    freeze_id: str
    itinerary_id: str
    market_price_cents: int
    claim_status: str
    overshoot_cents: int
    capped_impact_cents: int
    payout_cents: int
    transaction_value_cents: int
    transaction_value_pre_cents: int
    transaction_value_final_cents: int
    audit_ready: bool
    depth_ratio: float
    continuum_absorbed_cents: int
    filer_user_id: str
    approver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeEvent(TypedDict, total=False):
    id: str
    protection_id: str
    itinerary_id: str
    old_departure_date: str
    new_departure_date: str
    day_shift: int
    disruption_days: int
    unrecovered_travel_fare_cents: int
    remaining_days: int
    status: str
    selected_option_id: Optional[str]
    option_hold_expires_at: Optional[str]
    gap_direction: str
    created_at: str
    updated_at: str
    version: int


class RebookingOption(TypedDict, total=False):
    id: str
    change_event_id: str
    departure_date: str
    option_fare_cents: int
    sequence_index: int
    hold_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    itinerary_id: str
    freeze_id: Optional[str]
    protection_id: Optional[str]
    claim_id: Optional[str]
    payment_kind: str
    amount_cents: int
    refundable_remaining_cents: int
    status: str
    retired_reason: str
    allocations: List[dict]
    created_at: str
    updated_at: str
    version: int


class HedgingPosition(TypedDict, total=False):
    id: str
    route_id: str
    coverage_date: str
    hedge_price_cents: int
    contract_quantity_cents: int
    status: str
    projected_day_cost_cents: int
    pool_id: str
    mark_value_cents: int
    regression_reversed: bool
    absorption_released_cents: int
    pool_binding_count: int
    created_at: str
    updated_at: str
    version: int


class RiskPool(TypedDict, total=False):
    id: str
    region: str
    pool_code: str
    absorbed_regression_cents: int
    available_capacity_cents: int
    bound_position_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DestinationOption(TypedDict, total=False):
    id: str
    itinerary_id: str
    departure_date: str
    option_fare_cents: int
    direction: str
    eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int