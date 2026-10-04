"""Domain thresholds and test defaults for the homebuilder mortgage capture API.

Every number here is normative in the PRD: monetary values are integer cents,
rates and ratios are integer basis points, and the clock starts at the fixed
2026-09-01T00:00:00Z instant rather than at wall-clock time.
"""

# The instant the logical clock reports on a fresh deployment.
BASE_CLOCK = "2026-09-01T00:00:00Z"

# --- capture rate realization ---
CAPTURE_RATE_TARGET_DEFAULT_BPS = 8500
SUSPEND_CAPTURE_SHORTFALL_BPS = 2000

# --- mortgage qualification scoring ---
INCOME_CAP_CENTS = 2_000_000
QUALIFY_SCORE_FLOOR = 620
DTI_QUALIFY_CEILING_BPS = 4500
PREMIUM_INCOME_TIER_CENTS = 1_200_000
STANDARD_INCOME_TIER_CENTS = 900_000
QUALIFICATION_VALID_DAYS = 120
SCORE_MIN = 300
SCORE_MAX = 850

# --- incentive allocation waterfall ---
PRIORITY_ORDER = ("PRICE_REDUCTION", "CLOSING_COSTS", "RATE_BUYDOWN")

# --- buydown cost recognition ---
RECAPTURE_WINDOW_DAYS = 365

# --- lock economics ---
FREE_EXTENSION_DAYS = 15
MID_TIER_DAYS = 15
MID_TIER_RATE_CENTS_PER_DAY = 45
HIGH_TIER_RATE_CENTS_PER_DAY = 110
RELOCK_FLAT_FEE_CENTS = 120_000
MAX_RELOCKS = 2

# --- disclosure cure window ---
CURE_GRACE_DAYS = 3

# --- deposit forfeiture ---
PARTIAL_FORFEITURE_BPS = 500
TIER_SHIFT_GUARD_CENTS = 500_000

# --- forward commitment pool ---
PAIR_OFF_FEE_PER_UNIT_CENTS = 95_000

# --- jurisdiction maps used by the deposit statute selector ---
FULL_FORFEITURE_STATES = ("FL", "TX")
PARTIAL_FORFEITURE_STATES = ("CA", "NY", "IL")
UNMAPPED_STATE = "OH"

# Defaults the tests lean on when a bucket cap is not the subject of the test.
STANDARD_CAPS = {
    "price_reduction_cap_cents": 3_000_000,
    "closing_cost_cap_cents": 2_000_000,
    "rate_buydown_cap_cents": 6_000_000,
}
PREMIUM_CAPS = {
    "price_reduction_cap_cents": 4_000_000,
    "closing_cost_cap_cents": 2_500_000,
    "rate_buydown_cap_cents": 8_000_000,
}

# Defaults for inventory and deal arithmetic.
DEFAULT_BASE_PRICE_CENTS = 50_000_000
DEFAULT_PURCHASE_PRICE_CENTS = 50_000_000
DEFAULT_EARNEST_MONEY_CENTS = 2_000_000
DEFAULT_ADVERTISED_RATE_BPS = 499
DEFAULT_LOCK_RATE_BPS = 499
DEFAULT_COMMITTED_RATE_BPS = 499
DEFAULT_QUALIFYING_INCOME_CENTS = 2_000_000
DEFAULT_MONTHLY_DEBT_CENTS = 100_000