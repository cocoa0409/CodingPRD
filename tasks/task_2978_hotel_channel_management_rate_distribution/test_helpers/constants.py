"""Named constants drawn from the Hotel Channel Distribution API contract.

Every value here is written in the contract itself: the five role names, the
enumerated members of every declared enum, the policy defaults that apply when
an optional field is omitted, and the named numeric limits the contract spells
out (the derivation cap, the job attempt cap, the suspension threshold, the
loyalty tier floors, the pace window and the mix minimum).
"""

from typing import Dict, List

# ── Roles ──────────────────────────────────────────────────────────────────

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_REVENUE_MANAGER = "RevenueManager"
ROLE_REVENUE_DIRECTOR = "RevenueDirector"
ROLE_CHANNEL_OPS_ENGINEER = "ChannelOpsEngineer"
ROLE_CHANNEL_PARTNER = "ChannelPartner"

DECLARED_ROLES: List[str] = [
    ROLE_PLATFORM_ADMIN,
    ROLE_REVENUE_MANAGER,
    ROLE_REVENUE_DIRECTOR,
    ROLE_CHANNEL_OPS_ENGINEER,
    ROLE_CHANNEL_PARTNER,
]

INTERNAL_ROLES: List[str] = [
    ROLE_PLATFORM_ADMIN,
    ROLE_REVENUE_MANAGER,
    ROLE_REVENUE_DIRECTOR,
    ROLE_CHANNEL_OPS_ENGINEER,
]

# ── The logical clock ──────────────────────────────────────────────────────

# A fresh server starts here.
SERVER_START_CLOCK = "2026-08-01T00:00:00Z"
SERVER_START_CLOCK_CANONICAL = "2026-08-01T00:00:00.000Z"

# ── Enumerated values ──────────────────────────────────────────────────────

CURRENCY_CODE_USD = "USD"

CHANNEL_KINDS: List[str] = [
    "OTA_PUBLIC",
    "OTA_OPAQUE",
    "GDS",
    "DIRECT_BRAND",
    "WHOLESALER",
]

RATE_CLASSES: List[str] = ["PUBLIC", "NEGOTIATED", "OPAQUE", "PACKAGE"]

OFFSET_KINDS: List[str] = ["NONE", "PERCENT", "AMOUNT"]

PLAN_STATES: List[str] = ["DRAFT", "ACTIVE", "CLOSED"]

PROTOCOLS: List[str] = ["XML_PUSH", "JSON_PUSH", "ARI_PULL"]

CONNECTION_STATES: List[str] = [
    "PENDING",
    "HEALTHY",
    "DEGRADED",
    "SUSPENDED",
    "RETIRED",
]

SELLABLE_CONNECTION_STATES: List[str] = ["HEALTHY", "DEGRADED"]

HEARTBEAT_STATUSES: List[str] = ["OK", "ERROR"]

FAILURE_CODES: List[str] = [
    "TIMEOUT",
    "AUTH_REJECTED",
    "SCHEMA_ERROR",
    "MAPPING_REJECTED",
    "UNKNOWN",
]

FREEZE_REASONS: List[str] = ["MAINTENANCE", "CERTIFICATION", "INCIDENT"]

MAPPING_STATES: List[str] = ["DRAFT", "VERIFIED", "ERRORED", "DISABLED"]

PARITY_STATES: List[str] = ["UNKNOWN", "IN_PARITY", "OUT_OF_PARITY"]

MISMATCH_STATES: List[str] = ["UNKNOWN", "IN_SYNC", "MISMATCHED"]

PROMO_KINDS: List[str] = ["MEMBER_RATE", "PACKAGE_INCLUSION", "GEO_OFFER"]

# The fixed order in which stacked promotions are applied.
PROMO_STACK_ORDER: List[str] = ["MEMBER_RATE", "GEO_OFFER", "PACKAGE_INCLUSION"]

DISCOUNT_KINDS: List[str] = ["PERCENT", "AMOUNT"]

APPROVAL_STATUSES: List[str] = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]

DISTRIBUTION_STATUSES: List[str] = [
    "NOT_LOADED",
    "LOADING",
    "LOADED",
    "LOAD_FAILED",
]

RESTRICTION_TYPES: List[str] = ["MIN_STAY", "CLOSED_TO_ARRIVAL", "STOP_SELL"]

# The fixed order in which sell restrictions are tested against a stay.
RESTRICTION_TEST_ORDER: List[str] = ["STOP_SELL", "CLOSED_TO_ARRIVAL", "MIN_STAY"]

RESTRICTION_ORIGINS: List[str] = ["MANUAL", "AUTO_OVERBOOK_GUARD"]

RESTRICTION_STATES: List[str] = ["ACTIVE", "LIFTED"]

LIFT_REASONS: List[str] = ["MANUAL_LIFT", "AUTO_GUARD_CLEARED"]

ALLOCATION_STATES: List[str] = [
    "OPEN",
    "EXHAUSTED",
    "RELEASED",
    "RECALLED",
    "SUPERSEDED",
]

POOLED_STATES: List[str] = ["OPEN", "TIGHT", "EXHAUSTED", "OVERSOLD"]

RESERVATION_STATES: List[str] = ["CONFIRMED", "CANCELLED"]

PAYLOAD_KINDS: List[str] = ["RATE", "RESTRICTION", "PROMOTION"]

SOURCE_REF_KINDS: List[str] = ["RATE_PLAN", "RESTRICTION", "PROMOTION"]

BATCH_STATES: List[str] = [
    "QUEUED",
    "DISPATCHING",
    "APPLIED",
    "PARTIALLY_APPLIED",
    "FAILED",
]

JOB_STATES: List[str] = ["QUEUED", "DISPATCHED", "APPLIED", "REJECTED", "ABANDONED"]

JOB_FAILURE_REASONS: List[str] = [
    "CONNECTION_UNAVAILABLE",
    "MAPPING_NOT_VERIFIED",
    "PARITY_BLOCKED",
    "MAPPING_DISABLED",
    "CONNECTION_UNHEALTHY",
    "FREEZE_WINDOW_ACTIVE",
]

PERFORMANCE_BASES: List[str] = ["STAY", "BOOKED"]

PACE_BASELINES: List[str] = ["ROLLING", "STLY"]

PACE_STATES: List[str] = ["NO_BASELINE", "AHEAD", "ON_PACE", "BEHIND"]

# ── Named numeric limits ───────────────────────────────────────────────────

MAX_DERIVATION_DEPTH = 2
MAX_JOB_ATTEMPTS = 3
CONNECTION_FAILURE_SUSPEND_THRESHOLD = 3
REVALIDATION_FAILURE_STREAK = 2
FREEZE_PRE_BUFFER_MINUTES = 60

PROMOTION_STACK_CAP_BP = 3000
PROMOTION_SUBMIT_MAX_DISCOUNT_BP = 3000

LOYALTY_TIER_1_FLOOR_CENTS = 50000
LOYALTY_TIER_2_FLOOR_CENTS = 70000
LOYALTY_TIER_0_BP = 0
LOYALTY_TIER_1_BP = 400
LOYALTY_TIER_2_BP = 600

PACE_BASELINE_WINDOW_DAYS = 7
STLY_OFFSET_DAYS = 364
PACE_AHEAD_BP = 11000
PACE_BEHIND_BP = 9000

MIN_MIX_ROOM_NIGHTS = 1

BASIS_POINT_SCALE = 10000

# ── Pagination ─────────────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ── Field defaults the contract states for omitted optional inputs ─────────

PROPERTY_DEFAULTS: Dict[str, object] = {
    "currency_code": CURRENCY_CODE_USD,
    "overbooking_pct_bp": 0,
    "booking_horizon_days": 365,
    "mix_window_days": 30,
    "rate_mismatch_tolerance_cents": 0,
    "required_image_count": 0,
}

ROOM_TYPE_DEFAULT_OVERBOOKING_PCT_BP = None

CHANNEL_DEFAULTS: Dict[str, object] = {
    "sell_adjustment_bp": 0,
    "allows_member_rate": False,
    "allows_opaque_rate": False,
    "geo_market_codes": [],
    "requires_content_parity": True,
}

CHANNEL_LEDGER_FIELDS: List[str] = [
    "gross_revenue_cents",
    "commission_accrued_cents",
    "net_revenue_cents",
    "room_nights_sold",
    "bookings_count",
    "cancellations_count",
    "mismatch_alert_count",
]

EMPTY_LEDGER: Dict[str, int] = {field: 0 for field in CHANNEL_LEDGER_FIELDS}

CONNECTION_DEFAULT_HEARTBEAT_INTERVAL_MINUTES = 15

RATE_PLAN_DEFAULTS: Dict[str, object] = {
    "parent_rate_plan_id": None,
    "offset_kind": "NONE",
    "offset_bp": None,
    "offset_amount_cents": None,
    "package_inclusion_cents": 0,
    "member_only": False,
    "negotiated_account_code": None,
}

MAPPING_CONTENT_DEFAULTS: Dict[str, object] = {
    "content_description_hash": None,
    "content_image_count": None,
}

PROMOTION_DEFAULTS: Dict[str, object] = {
    "discount_bp": None,
    "discount_amount_cents": None,
    "geo_market_codes": [],
}

RESERVATION_DEFAULTS: Dict[str, object] = {
    "member_flag": False,
    "geo_market_code": None,
    "negotiated_account_code": None,
    "override_overbooking": False,
}

# ── Common-field shapes ────────────────────────────────────────────────────

# Entities carrying id, created_at, updated_at and version.
VERSIONED_ENTITIES: List[str] = [
    "Property",
    "RoomType",
    "InventoryDay",
    "Channel",
    "ChannelConnection",
    "RatePlan",
    "ChannelMapping",
    "ChannelAllocation",
    "Restriction",
    "DistributionBatch",
    "RateDistributionJob",
    "Promotion",
    "Reservation",
]

# The single entity that carries only id and created_at.
CREATE_ONLY_ENTITIES: List[str] = ["ConnectivityFreezeWindow"]

PAGINATION_META_FIELDS: List[str] = ["limit", "offset", "total_count", "has_more"]
