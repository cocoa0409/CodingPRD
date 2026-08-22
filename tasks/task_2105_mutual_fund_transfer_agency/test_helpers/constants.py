"""Domain thresholds and precision tolerances used across the suite."""

# Rounding tolerances matching the PRD's four numeric conventions.
MONEY_TOLERANCE = 0.005      # dollars carried to exactly 2 decimal places
SHARE_TOLERANCE = 0.0005     # share quantities carried to exactly 3 decimal places
PRICE_TOLERANCE = 0.00005    # prices per share carried to exactly 4 decimal places
PCT_TOLERANCE = 0.00005      # percentages carried to 4 decimal places

THRESHOLDS = {
    "AS_OF_MAX_BUSINESS_DAYS": 3,
    "MATERIALITY_THRESHOLD_BPS": 50,
    "BACKUP_WITHHOLDING_RATE": 0.24,
    "CDSC_FREE_ALLOWANCE_PCT": 0.10,
    "CDSC_TIER_1_DAYS": 365,
    "CDSC_TIER_2_DAYS": 730,
    "CDSC_TIER_1_PCT": 0.0100,
    "CDSC_TIER_2_PCT": 0.0050,
    "RECON_TOLERANCE_FLOOR": 1.00,
    "RECON_TOLERANCE_RATE": 0.0001,
    "MAX_LOAD_PCT": 0.0850,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK_UTC": "2026-08-01T00:00:00Z",
    "DEFAULT_CUTOFF_TIME_UTC": "16:00:00",
    "DEFAULT_TWELVE_B_ONE_FEE_PCT": 0.0025,
    "FUND_FAMILY_CODE": "MER",
    "FUND_NAME": "Meridian Growth Fund",
    "SEED_NAV": 10.0000,
    "REGISTERED_AMOUNT": 1_000_000.00,
    "WINDOW_EFFECTIVE_DATE": "2026-01-01",
    "WINDOW_EXPIRATION_DATE": "2027-01-01",
}

# Business dates used throughout: 2026-08-01 is a Saturday, 2026-08-03 a Monday.
SATURDAY = "2026-08-01"
MONDAY = "2026-08-03"
TUESDAY = "2026-08-04"
WEDNESDAY = "2026-08-05"
THURSDAY = "2026-08-06"
FRIDAY = "2026-08-07"

# The three-tier breakpoint schedule used by most pricing scenarios.
DEFAULT_BREAKPOINT_TIERS = [
    {"min_qualifying_amount": 0, "load_pct": 0.0575},
    {"min_qualifying_amount": 50000, "load_pct": 0.045},
    {"min_qualifying_amount": 100000, "load_pct": 0.035},
]

# A two-tier schedule for scenarios that never reach the 100000 breakpoint.
TWO_TIER_BREAKPOINT_TIERS = [
    {"min_qualifying_amount": 0, "load_pct": 0.0575},
    {"min_qualifying_amount": 50000, "load_pct": 0.045},
]

# A flat schedule with no front-end load at all.
NO_LOAD_BREAKPOINT_TIERS = [{"min_qualifying_amount": 0, "load_pct": 0.0}]

# A single-tier schedule charging the entry load on every dollar.
SINGLE_TIER_BREAKPOINT_TIERS = [{"min_qualifying_amount": 0, "load_pct": 0.0575}]
