"""Domain constants for the Oilseed Crush Origination API.

Every numeric literal in this module is pinned to a verbatim PRD.md statement;
the PRD section is quoted next to each constant. Do not change a value without
re-checking the cited PRD sentence — a drifted constant poisons every test
built on these helpers.
"""

# --- Logical clock (PRD §2.5) ---------------------------------------------------
# "At startup the clock reads exactly 2026-09-01T00:00:00Z."
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# --- Crush yield constants (PRD §3.6) -------------------------------------------
# "Expected yields come off the standard crush: eleven pounds of oil per bushel
#  land in expected_oil_lbs and forty-seven pounds of meal per bushel land in
#  expected_meal_lbs."
OIL_YIELD_LBS_PER_BUSHEL = 11
MEAL_YIELD_LBS_PER_BUSHEL = 47

# --- Board crush hedge sizing (PRD §3.7) ----------------------------------------
# "locked_margin_cents is that spread multiplied by bean_lots_long multiplied by
#  five thousand bushels per bean futures contract, rounded half up to whole
#  cents."
BEAN_CONTRACT_BUSHELS = 5000

# --- Carry assessment storage cost (PRD §3.3) -----------------------------------
# "...and charges five cents per bushel per month of storage across the gap."
CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH = 5

# --- Sales delivery window (PRD §3.8) -------------------------------------------
# "the end must come after the start and the span must not exceed sixty-two
#  days, otherwise ERR_DELIVERY_WINDOW_INVALID."
MAX_DELIVERY_WINDOW_DAYS = 62

# --- Default claims and buyer suspension (PRD §3.9) -----------------------------
# "Each default sets claim_cents to the undelivered pounds multiplied by
#  price_cents_per_lb multiplied by ten percent, rounded half up to whole cents"
DEFAULT_CLAIM_RATE = 0.10
# "...and suspends the buyer — ACTIVE to SUSPENDED, terminal — the moment the
#  count reaches three open claims."
BUYER_SUSPEND_CLAIM_THRESHOLD = 3

# --- Biodiesel feedstock quota horizon (PRD §3.8) -------------------------------
# "...multiplied by its biodiesel_feedstock_share_pct divided by one hundred,
#  multiplied across a thirty-day horizon — a breach is
#  ERR_FEEDSTOCK_QUOTA_EXCEEDED."
FEEDSTOCK_QUOTA_DAYS = 30

# --- Pagination defaults (PRD §2.3) ---------------------------------------------
# "limit sets the maximum number of items returned: it defaults to 10 when
#  omitted, accepts a minimum of 1, and is capped at 100. offset sets the number
#  of items skipped and defaults to 0."
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Precision discipline (PRD §2.7) --------------------------------------------
# "Monetary amounts are integer cents everywhere ... Bushel quantities carry
#  exactly three decimal places, and crush spreads per bushel carry exactly two.
#  All rounding in the system is round half up"
BUSHELS_DECIMALS = 3
SPREAD_DECIMALS = 2

# Grouped view for tests that iterate thresholds.
THRESHOLDS = {
    "OIL_YIELD_LBS_PER_BUSHEL": OIL_YIELD_LBS_PER_BUSHEL,
    "MEAL_YIELD_LBS_PER_BUSHEL": MEAL_YIELD_LBS_PER_BUSHEL,
    "BEAN_CONTRACT_BUSHELS": BEAN_CONTRACT_BUSHELS,
    "CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH": CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH,
    "MAX_DELIVERY_WINDOW_DAYS": MAX_DELIVERY_WINDOW_DAYS,
    "DEFAULT_CLAIM_RATE": DEFAULT_CLAIM_RATE,
    "BUYER_SUSPEND_CLAIM_THRESHOLD": BUYER_SUSPEND_CLAIM_THRESHOLD,
    "FEEDSTOCK_QUOTA_DAYS": FEEDSTOCK_QUOTA_DAYS,
    "PAGE_LIMIT_DEFAULT": PAGE_LIMIT_DEFAULT,
    "PAGE_LIMIT_MIN": PAGE_LIMIT_MIN,
    "PAGE_LIMIT_MAX": PAGE_LIMIT_MAX,
    "BUSHELS_DECIMALS": BUSHELS_DECIMALS,
    "SPREAD_DECIMALS": SPREAD_DECIMALS,
}

__all__ = [
    "LOGICAL_CLOCK_START",
    "OIL_YIELD_LBS_PER_BUSHEL",
    "MEAL_YIELD_LBS_PER_BUSHEL",
    "BEAN_CONTRACT_BUSHELS",
    "CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH",
    "MAX_DELIVERY_WINDOW_DAYS",
    "DEFAULT_CLAIM_RATE",
    "BUYER_SUSPEND_CLAIM_THRESHOLD",
    "FEEDSTOCK_QUOTA_DAYS",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MIN",
    "PAGE_LIMIT_MAX",
    "PAGE_OFFSET_DEFAULT",
    "BUSHELS_DECIMALS",
    "SPREAD_DECIMALS",
    "THRESHOLDS",
]
