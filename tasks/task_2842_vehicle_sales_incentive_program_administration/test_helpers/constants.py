"""Domain thresholds and shared literals drawn from the PRD's calculations."""

# --- Named numeric constants -------------------------------------------------
# PRD §3.7: the market benchmark APR of 799 basis points.
MARKET_APR_BPS = 799
# PRD §3.9: the flat cancellation reserve of 275 basis points (2.75 percent).
CANCEL_RESERVE_BPS = 275
# PRD §3.3: the system ceiling of 5000 basis points on the total objective uplift.
MAX_TOTAL_UPLIFT_BPS = 5000
# PRD §3.3: objective_units is raised to 1 when the rounding produced less.
MIN_OBJECTIVE_UNITS = 1
# PRD §3.5: a reporting lag strictly greater than ten days is back-dated.
MAX_REPORT_LAG_DAYS = 10
# PRD §3.9: the residual pass-through factor of 6000 basis points.
RESIDUAL_PASS_THROUGH_BPS = 6000
# PRD §3.4: protest_round must be strictly less than two to file again.
MAX_PROTEST_ROUNDS = 2
# PRD §3.8: the gap between adjacent pay periods must exceed one whole day.
SETTLEMENT_BUFFER_DAYS = 1

# Declared input ceilings (PRD §3.1 and §3.3).
MAX_APR_BUYDOWN_BPS = 2000
MAX_RESIDUAL_SUPPORT_BPS = 1500
MAX_PROJECTED_TAKE_RATE_BPS = 10000
MAX_MARKET_OPPORTUNITY_BPS = 20000
MAX_STRETCH_BPS = 10000
BPS_DENOMINATOR = 10000
FINANCE_LEG_DENOMINATOR = 120000

# --- Pagination (PRD §2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- The logical clock (PRD §2.6) -------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

# Convenient instants for the August 2026 test calendar.
AUG_01 = "2026-08-01T00:00:00.000Z"
AUG_16 = "2026-08-16T00:00:00.000Z"
AUG_31 = "2026-08-31T00:00:00.000Z"
SEP_01 = "2026-09-01T00:00:00.000Z"
BUILD_FROM = "2026-05-01T00:00:00.000Z"
BUILD_TO = "2026-07-31T00:00:00.000Z"

TEST_DEFAULTS = {
    "PER_UNIT_AMOUNT_CENTS": 150000,
    "BUDGET_CENTS": 90000000,
    "MSRP_CENTS": 3200000,
    "MODEL_CODE": "MX5",
    "TRIM_CODE": "BASE",
    "REGION_CODE": "WEST",
    "HISTORICAL_VOLUME_UNITS": 6,
}


def iso_day(year: int, month: int, day: int) -> str:
    """Render a calendar day as an ISO 8601 UTC instant with three fractional digits."""
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00.000Z"
