"""Closed vocabularies and business constants (PRD 2.10, 3.x)."""

from decimal import Decimal

ROLES = (
    "AgencyPlanner",
    "AgencyBuyer",
    "AgencyController",
    "SellerRep",
    "AdvertiserClient",
    "MeasurementProvider",
)

ALL_ROLES = list(ROLES)

CHANNELS = ("LINEAR_TV", "CTV", "DIGITAL_VIDEO", "AUDIO")
PLATFORMS = ("LINEAR", "CTV", "DIGITAL", "AUDIO")
MARKETS = ("UPFRONT", "SCATTER")
DAYPARTS = ("PRIME", "DAYTIME", "LATE", "DIGITAL_ANY")
CATEGORY_CODES = (
    "BEVERAGE",
    "AUTOMOTIVE",
    "PHARMA",
    "RETAIL",
    "FINANCE",
    "TELECOM",
    "GROCERY",
    "INSURANCE",
    "TRAVEL",
    "BEAUTY",
    "FITNESS",
    "TECHNOLOGY",
    "HOME",
    "ELECTRONICS",
)
MEASUREMENT_BASES = ("LINEAR_C3", "DIGITAL_VAST", "CTV_SERVER")
EXCLUSIVITY_MODES = ("SHARED", "EXCLUSIVE")
MAKE_GOOD_PROVISIONS = ("MAKE_GOOD_UNITS", "CASH_CREDIT", "NONE")
OFFER_ACTORS = ("AGENCY", "SELLER")
RIGHTS_KINDS = ("OPTION_ROLL", "CANCELLATION")
DEDUP_METHODS = ("SEQUENTIAL_DEDUP", "AGGREGATE_DEDUP")
AIRING_OUTCOMES = ("AIRED", "PREEMPTED")

CREDIT_STATUSES = ("ACTIVE", "WATCH", "HOLD")
PLAN_STATUSES = ("DRAFT", "PENDING_CLIENT_APPROVAL", "APPROVED", "REVISION_REQUIRED")
FUNDING_STATUSES = ("UNFUNDED", "PARTIALLY_FUNDED", "FUNDED")
PLAN_POSTURES = ("WITHIN_PLAN", "REPLAN_REQUIRED")
ALLOCATION_STATUSES = ("DRAFT", "LOCKED")
ALLOCATION_POSTURES = ("WITHIN_PLAN", "OVERCOMMITTED")
FORECAST_STATUSES = ("DRAFT", "PUBLISHED", "EXHAUSTED")
NEGOTIATION_STATUSES = ("AGENCY_OFFER", "SELLER_COUNTER", "ACCEPTED", "WITHDRAWN")
BUY_STATUSES = (
    "PENDING_PLACEMENT",
    "PLACED",
    "IN_FLIGHT",
    "COMPLETED",
    "CLOSED",
    "CANCELLED",
)
STEWARDSHIP_STATUSES = (
    "NOT_STARTED",
    "ON_TRACK",
    "AT_RISK",
    "UNDER_DELIVERED",
    "WITHIN_TOLERANCE",
    "MADE_GOOD",
)
SETTLEMENT_STATUSES = ("UNBILLED", "INVOICED", "CLIENT_PAID", "REMITTED")
UNIT_STATUSES = (
    "SCHEDULED",
    "AIRED",
    "PREEMPTED",
    "CANCELLED",
    "MAKE_GOOD_SCHEDULED",
    "MAKE_GOOD_AIRED",
)
REPORT_STATUSES = ("SUBMITTED", "ACCEPTED", "DISPUTED")
MAKE_GOOD_STATUSES = ("OPEN", "OFFERED", "SCHEDULED", "WAIVED")
INVOICE_CLIENT_STATUSES = ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID")
INVOICE_SELLER_STATUSES = ("UNREMITTED", "PARTIALLY_REMITTED", "REMITTED")
RUN_STATUSES = ("COMPLETED", "COMPLETED_NO_DATA")

# --- statuses that consume / commit -----------------------------------------
COMMITTED_BUY_STATUSES = ("PLACED", "IN_FLIGHT", "COMPLETED", "CLOSED")
HOLDING_UNIT_STATUSES = ("SCHEDULED", "AIRED", "MAKE_GOOD_SCHEDULED", "MAKE_GOOD_AIRED")

# --- planning ---------------------------------------------------------------
MARKET_MULTIPLIER = {"UPFRONT": Decimal("1.00"), "SCATTER": Decimal("1.35")}
DAYPART_INDEX = {
    "PRIME": Decimal("1.20"),
    "DAYTIME": Decimal("0.85"),
    "LATE": Decimal("0.70"),
    "DIGITAL_ANY": Decimal("1.00"),
}
CPM_BAND_LOW = Decimal("0.60")
CPM_BAND_HIGH = Decimal("2.50")
CPM_ABS_FLOOR_CENTS = 200
CPM_ABS_CEIL_CENTS = 12000
ALLOCATION_PCT_TOTAL = Decimal("100.00")

# --- buy cost ---------------------------------------------------------------
COMMISSION_TIER_SMALL_RATE = Decimal("0.0700")
COMMISSION_TIER_MID_RATE = Decimal("0.0550")
COMMISSION_TIER_LARGE_RATE = Decimal("0.0400")
COMMISSION_TIER_MID_FLOOR_CENTS = 5000000
COMMISSION_TIER_LARGE_FLOOR_CENTS = 25000000

# --- negotiation / make-good bounds ----------------------------------------
MAX_NEGOTIATION_ROUNDS = 6
MAX_MAKE_GOOD_OFFERS = 3
MAKE_GOOD_TOLERANCE_PCT = Decimal("2.0000")

# --- rights windows ---------------------------------------------------------
OPTION_WINDOW_DAYS = 45
CANCEL_WINDOW_1_DAYS = 60
CANCEL_WINDOW_2_DAYS = 30
CANCEL_CEILING_EARLY_PCT = Decimal("100.00")
CANCEL_CEILING_LATE_PCT = Decimal("25.00")

# --- placement --------------------------------------------------------------
CATEGORY_SEPARATION_DAYS = 7

# --- reconciliation ---------------------------------------------------------
GROUP_ORDER = ("LINEAR", "CTV", "DIGITAL")
CHANNEL_GROUP = {
    "LINEAR_TV": "LINEAR",
    "CTV": "CTV",
    "DIGITAL_VIDEO": "DIGITAL",
    "AUDIO": "DIGITAL",
}

# --- unit / avail platform compatibility ------------------------------------
CHANNEL_PLATFORM = {
    "LINEAR_TV": "LINEAR",
    "CTV": "CTV",
    "DIGITAL_VIDEO": "DIGITAL",
    "AUDIO": "AUDIO",
}

# --- pagination -------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

# --- logical clock ----------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"
