"""Every numeric constant the PRD pins, in one place."""

from decimal import Decimal

# --- roles / headers -------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "OperationsCoordinator",
    "TransactionCoordinator",
    "ListingAgent",
    "AssociateAgent",
)
ENTITY_BACKED_ROLES = ("ListingAgent", "AssociateAgent")

# --- band arithmetic -------------------------------------------------------
NEAR_TARGET_BAND_MIN = Decimal("0.75")
OVER_TARGET_BAND_MIN = Decimal("1.00")
OVER_TARGET_VETO_CEILING = Decimal("1.25")
DEFAULT_TARGET_CLIENT_RATIO = Decimal("1.0")

# --- compensation ----------------------------------------------------------
BONUS_CLOSE_WEIGHT = Decimal("0.2")
BONUS_CSAT_WEIGHT = Decimal("0.15")
BONUS_OCCUPANCY_WEIGHT = Decimal("0.1")
BONUS_PCT_CAP = Decimal("0.30")
BONUS_MIN_CLOSED_TRANSACTIONS = 3
SATISFACTION_INCLUDED_STATES = ("RESPONDED",)

REFERRAL_FEE_CAP_BPS = 2500
REFERRAL_FEE_BPS_PER_10K_SALARY_CENTS = 1
REFERRAL_PARTNER_CAPACITY = 3

# --- listings --------------------------------------------------------------
LIST_FEE_RATE_CEILING = Decimal("0.015")
MIN_LIST_PRICE_CENTS = 10000000
MARGINAL_TIER_BREAKS = (50000000, 100000000, 200000000)
MARGINAL_TIER_RATES = (Decimal("0.015"), Decimal("0.0125"), Decimal("0.010"))
TRAILING_SLICE_BREAKS = (33333333, 100000000, 200000000)
TRAILING_SLICE_HOURS = (Decimal("0.0147"), Decimal("0.0113"), Decimal("0.0091"))

FULL_SERVICE_HOURS = 24
LIMITED_SERVICE_HOURS = 48
MLS_ONLY_HOURS = 0
BREACH_REVISION_HOURS = 24
LISTING_WINDOW_DAYS = 30

# --- tours -----------------------------------------------------------------
ACCESS_CODE_RELEASE_LEAD_MINUTES = 120
NO_SHOW_GRACE_MINUTES = 30
TOUR_WINDOW_DAYS = 7
TOUR_BLOCK_MINUTES = 60
TOUR_LOAD_BAND_EDGES = (0, 1, 5)
ASSOCIATE_CAPACITY_LIMIT = 4

# --- referrals -------------------------------------------------------------
MAX_REFERRAL_FEE_BPS = 2500

# --- transactions ----------------------------------------------------------
SATISFACTION_CREDIT = Decimal("0.05")
SATISFACTION_CREDIT_WINDOW_DAYS = 180
COORDINATION_RECONCILE_WINDOW_HOURS = 36

# --- pagination (meta field names / defaults) ------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

ALLOWED_ENUMS = {
    "agent_kind": ("LEAD", "ASSOCIATE"),
    "agent_status": ("ACTIVE", "AT_CAPACITY", "ON_LEAVE"),
    "need_kind": ("BUY", "SELL"),
    "coordination_status": ("UNASSIGNED", "ASSIGNED", "REVIEW", "CLOSED", "CANCELLED"),
    "service_tier": ("FULL_SERVICE", "LIMITED_SERVICE", "MLS_ONLY"),
    "tour_status": ("ACCESS_PENDING", "CONFIRMED", "COMPLETED", "CANCELLED_NO_SHOW", "CANCELLED"),
    "split_policy": ("SPLIT_25_PARTNER", "SPLIT_50_PARTNER"),
    "response_status": ("DISPATCHED", "RESPONDED", "EXPIRED_DISPATCH"),
    "settlement_status": ("PENDING", "COMPUTED", "SETTLED"),
}

SERVICE_TIER_HOURS = {
    "FULL_SERVICE": FULL_SERVICE_HOURS,
    "LIMITED_SERVICE": LIMITED_SERVICE_HOURS,
    "MLS_ONLY": MLS_ONLY_HOURS,
}

SPLIT_SHARES = {
    "SPLIT_25_PARTNER": Decimal("0.25"),
    "SPLIT_50_PARTNER": Decimal("0.50"),
}

PIPELINE_CLIENT_STATES = ("UNASSIGNED", "ASSIGNED", "IN_TRANSACTION")
ACTIVE_AGENT_STATES = ("ACTIVE", "AT_CAPACITY")
OPEN_TRANSACTION_STATES = ("UNASSIGNED", "ASSIGNED", "REVIEW")