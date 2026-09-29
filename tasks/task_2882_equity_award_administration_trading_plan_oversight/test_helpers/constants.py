"""Domain thresholds and pinned numeric constants drawn from the PRD."""

# Logical clock (PRD §2.5)
CLOCK_BOOT_INSTANT = "2026-08-01T00:00:00Z"

# Basis points (PRD §2.8)
BPS_FULL = 10000

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Plan defaults (PRD §3.1)
PLAN_DEFAULTS = {
    "current_fiscal_year_label": "FY2026",
    "evergreen_pct_bps": 0,
    "evergreen_cap_shares": 0,
    "burn_rate_limit_bps": 10000,
    "fungible_ratio_full_value_bps": 10000,
    "low_reserve_threshold_bps": 0,
    "next_earnings_release_at": None,
}

PLAN_NAME_MIN_LENGTH = 1
PLAN_NAME_MAX_LENGTH = 120

# Retirement eligibility (PRD §3.3)
MIN_RETIREMENT_AGE_YEARS = 55
RULE_OF_POINTS = 65

# Grant revision cycle (PRD §3.4)
MAX_GRANT_REVISIONS = 2

# Performance payout tiers (PRD §3.6): lower edges are inclusive.
ZERO_PAYOUT_RATIO = "0.800000"
PAYOUT_TIERS = [
    ("0.000000", 0),
    ("0.800000", 5000),
    ("0.900000", 7500),
    ("1.000000", 10000),
    ("1.100000", 15000),
    ("1.200000", 20000),
]
PAYOUT_RATIO_DECIMALS = 6

# Settlement mechanics (PRD §3.7)
SELL_TO_COVER_COMMISSION_CENTS = 25

# Post-termination exercise period, in days (PRD §3.8)
PTEP_DAYS = {
    "FOR_CAUSE": 0,
    "VOLUNTARY": 90,
    "INVOLUNTARY": 180,
    "RETIREMENT": 1095,
    "DEATH": 365,
}

# Retirement acceleration window (PRD §3.8)
RETIREMENT_ACCELERATION_WINDOW_DAYS = 365

# Trading calendar (PRD §3.9)
WINDOW_BUFFER_HOURS = 48
PRECLEARANCE_VALIDITY_DAYS = 5
MAX_PRECLEARANCE_REVISIONS = 2
MAX_TRADING_PLAN_MODIFICATIONS = 2

# Cooling-off period, in days (PRD §3.9)
COOLING_OFF_DAYS = {
    "NON_INSIDER": 0,
    "DESIGNATED_INSIDER": 30,
}
SECTION_16_COOLING_OFF_MIN_DAYS = 90
SECTION_16_COOLING_OFF_MAX_DAYS = 120
EARNINGS_RELEASE_BUSINESS_DAY_OFFSET = 2

# Section 16 filing deadline (PRD §3.9)
REPORT_DUE_BUSINESS_DAYS = 2
REPORT_DUE_TIME_OF_DAY = "23:59:59.999Z"

# Convenient defaults for test payloads.
TEST_DEFAULTS = {
    "TOTAL_AUTHORIZED_SHARES": 1_000_000,
    "COMMON_SHARES_OUTSTANDING": 1_000_000,
    "FISCAL_YEAR_START_DATE": "2026-01-01",
    "TARGET_SHARES": 1000,
    "EXERCISE_PRICE_CENTS": 2500,
    "FMV_PER_SHARE_CENTS": 5000,
    "TAX_RATE_BPS": 4000,
}

# The canonical identifier used for a row that does not exist.
UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"
