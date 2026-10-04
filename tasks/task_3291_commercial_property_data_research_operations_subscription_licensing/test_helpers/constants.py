"""Domain thresholds and constants named by the PRD's calculations."""

# Data-quality scoring (§3.4)
SOURCE_FRESHNESS_DAYS = 180
WEIGHT_VERIFIED_SOURCED = 1.0
WEIGHT_VERIFIED_UNSOURCED = 0.6
WEIGHT_UNVERIFIED = 0.0
WEIGHT_STALE_PENALTY = 0.1

# Seat metering (§3.10)
INCLUDED_ACTIVE_DAYS = 2
TIER_1_DAILY_RATE_CENTS = 1250
TIER_2_DAILY_RATE_CENTS = 900
TIER_3_DAILY_RATE_CENTS = 600
LICENSED_MARKET_USAGE_LIMIT_BPS = 250

# Market-addition pricing (§3.10)
MARKET_ADD_BASE_PCT = 0.08

# Capitalization (§3.5)
SUBSTITUTE_INCOME_CENTS = 250_000_000

# Enforcement (§3.7)
LITIGATION_PENALTY_THRESHOLD_CENTS = 75_000_000

# Forecast (§3.5)
BASE_GROWTH_RATE = 0.015
MIN_GROWTH_FACTOR = 0.90
MAX_GROWTH_FACTOR = 1.35
DEFAULT_HORIZON_QUARTERS = 4

# Listing product (§3.8)
LISTING_TTL_DAYS = 90
MAX_OFFICE_INDUSTRIAL_RENT_PSF = 500.00

# Shared fixture instants. The logical clock starts at 2026-09-01T00:00:00Z;
# fixtures that need a specific "now" set it through the clock endpoint.
CLOCK_EPOCH = "2026-09-01T00:00:00Z"

# Sensible payload defaults for factories.
TEST_DEFAULTS = {
    "MARKET": "TX-DALLAS",
    "SECOND_MARKET": "TX-HOUSTON",
    "ORG_LEGAL_NAME": "Tarrant Field Research LLC",
    "HOME_MARKET": "TX-DALLAS",
    "ANNUAL_FEE_CENTS": 100_000,
    "SEAT_COUNT": 5,
    "RENTABLE_SQFT": 120_000,
    "GROSS_SALE_PRICE_CENTS": 5_000_000_000,
    "AVAILABLE_SQFT": 42_000,
    "MONTHLY_RENT_PSF": 34.0,
    "DURATION_DAYS": 90,
}