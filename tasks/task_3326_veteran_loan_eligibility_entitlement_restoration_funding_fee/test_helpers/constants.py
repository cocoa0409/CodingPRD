"""Domain thresholds and numeric constants from the PRD (§2.6, §3)."""
from __future__ import annotations

# §2.6 — entitlement accounting constants (integer cents).
BASIC_ENTITLEMENT_CENTS = 3_600_000          # $36,000.00
COUNTY_LIMIT_CENTS = 76_655_000              # $766,550.00
GUARANTY_FRACTION = 0.25
BONUS_CAPACITY_CENTS = COUNTY_LIMIT_CENTS // 4   # 19,163,750 == $191,637.50

# §3.2 — COE service-length gates (days).
MIN_DAYS_REGULAR_MILITARY = 90
MIN_DAYS_RESERVES_NATIONAL_GUARD = 180
RECONSIDERATION_CAP = 2

# §3.3 — funding fee tier rates (percent).
FEE_FIRST_USE_LT5 = 2.15
FEE_FIRST_USE_5_TO_10 = 1.50
FEE_GE10 = 1.25
FEE_SUBSEQUENT_LT5 = 3.30
FEE_IRRRL = 0.50
FEE_CASHOUT_FIRST = 2.15
FEE_CASHOUT_SUBSEQUENT = 3.30
TIER_BOUNDARY_LOW_PCT = 5.0000
TIER_BOUNDARY_HIGH_PCT = 10.0000

# §3.4 — underwriting.
DTI_LIMIT_PERCENT = 41.00
COMPENSATING_FACTOR = 1.2
RESIDUAL_TABLE = {
    "NORTHEAST": [45000, 75500, 90900, 102500, 106200],
    "MIDWEST": [44100, 73800, 88900, 100300, 103900],
    "SOUTH": [44100, 73800, 88900, 100300, 103900],
    "WEST": [49100, 82300, 99000, 111700, 115800],
}
OVER_FIVE_STEP_CENTS = 8000

# §3.6 — occupancy.
MOVE_IN_DEADLINE_DAYS = 60

# §3.8 — refinance seasoning / NTB.
SEASONING_DAYS = 210
IRRRL_FEE_RATE = 0.50
RECOUPMENT_LIMIT_MONTHS = 36
NTB_FIXED_TO_FIXED = 0.50
NTB_FIXED_TO_ARM = 2.00
TERM_MONTHS = 360
NON_POSITIVE_SAVINGS_RECOUPMENT = 999999

# Logical clock startup default (§2.5).
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# Common fixture dates (days arithmetic is pinned by the PRD's closed-interval rule).
STANDARD_PERIOD_START = "2020-01-10"
STANDARD_PERIOD_END = "2022-06-15"          # 888 qualifying days
STANDARD_CLOSE_DATE = "2026-03-10"
STANDARD_FIRST_PAYMENT = "2026-05-01"
STANDARD_DEADLINE = "2026-05-09"            # closing + 60 days (inclusive)

STANDARD_DECISION_PAYLOAD = {
    "gross_monthly_income_cents": 600000,
    "new_housing_payment_cents": 150000,
    "other_obligations_annual_cents": [],
    "family_size": 4,
    "region": "SOUTH",
}

TEST_DEFAULTS = {
    "SSN_LAST4": "4000",
    "SERVICE_CATEGORY": "REGULAR_MILITARY",
    "DISCHARGE": "HONORABLE",
    "PURPOSE": "PURCHASE",
    "REGION": "SOUTH",
    "PRICE_CENTS": 30000000,
    "RATE": 6.5,
    "RATE_TYPE": "FIXED",
}
