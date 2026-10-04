"""Domain thresholds and shared literals from the PRD."""

# Logical clock default at server boot (PRD §2.4).
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Standard community geography used across fixtures.
MARKET_CODE = "DFW"
COMMUNITY_NAME = "Community A"
PARCEL_NAME = "Parcel A"
ACRES = 100.0
ABSORPTION_TARGET_PER_MONTH = 3.0
MONTHS_SUPPLY_TARGET = 3.0

# Standard series band (CLASSIC) used across fixtures.
SERIES_CODE = "CLASSIC"
SERIES_MIN_PRICE_CENTS = 30_000_000
SERIES_MAX_PRICE_CENTS = 50_000_000

# Standard option contract commercial terms.
OPTION_FEE_CENTS = 500_000
EARNEST_MONEY_CENTS = 1_000_000
TOTAL_LOTS = 40
LOT_BASE_PRICE_CENTS = 8_000_000

# Standard windows (logical-clock default is 2026-09-01T00:00:00Z).
SEP_WINDOW_START = "2026-09-01T00:00:00Z"
SEP_WINDOW_END = "2026-09-30T00:00:00Z"
SEP_PERIOD_START = "2026-09-01T00:00:00Z"
SEP_PERIOD_END_EXCLUSIVE = "2026-10-01T00:00:00Z"  # half-open capacity period end

# Standard home pricing.
HOME_BASE_PRICE_CENTS = 40_000_000

THRESHOLDS = {
    "OVERHELD_MONTHS_OF_SUPPLY": 4.0,
    "STARVED_MONTHS_OF_SUPPLY": 1.5,
    "ABSORPTION_FLOOR": 1.0,
    "STARVED_ALLOWANCE_FLOOR": 1,
    "CURE_FEE_PCT": 0.10,
    "ESCALATION_RATE_PER_QUARTER": 0.01,
    "QUARTER_DAYS": 91,
    "INCENTIVE_BUFFER_DAYS": 7,
}

# Stage multipliers by build stage (PRD §3.7).
STAGE_MULTIPLIERS = {
    "PERMITTED": 1.00,
    "FOUNDATION": 1.00,
    "FRAME": 1.01,
    "DRYWALL": 1.02,
    "COMPLETE": 1.03,
    "CLOSED": 1.03,
}

# Incentive stacking cap fraction by community phase (PRD §3.4).
CAP_PCT_BY_PHASE = {
    "PLANNING": 0.06,
    "OPEN_FOR_SALES": 0.06,
    "SELLING_OUT": 0.06,
    "CLOSE_OUT": 0.10,
    "CLOSED": 0.10,
}
