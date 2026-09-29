"""Numeric constants the PRD fixes for the destination-sales calculations."""

# --- logical clock -----------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

# --- economic impact ---------------------------------------------------------
DELEGATE_DAILY_SPEND = 285.00
EXHIBITOR_SPEND_PER_SQFT = 4.75
INDIRECT_MULTIPLIER = 1.65
LODGING_TAX_RATE = 0.15
OCCUPANCY_FACTOR = 1.6

# --- lead time and hold lifetimes (days) ------------------------------------
MIN_LEAD_DAYS = 180
FIRST_HOLD_DAYS = 90
PROMOTION_HOLD_DAYS = 30
CHALLENGE_DAYS = 14
DEFAULT_TURNAROUND_HOURS = 48
MAX_LIVE_HOLDS_PER_WINDOW = 2

# --- bid submission gates ----------------------------------------------------
COVERAGE_FLOOR_PCT = 85.00
CUTOFF_TOLERANCE_DAYS = 2
MIN_SUPPORT_LETTER_TYPES = 2
MAX_BID_ROUNDS = 3

# --- incentive cap ladder ----------------------------------------------------
BAND_1_NIGHTS = 5000
BAND_1_RATE = 12.00
BAND_2_NIGHTS = 15000
BAND_2_RATE = 8.00
BAND_3_RATE = 5.00

TIER_YIELD_RATE = {"TIER_A": 0.35, "TIER_B": 0.25, "TIER_C": 0.15}

COVERAGE_FACTOR_FULL_PCT = 95.00
COVERAGE_FACTOR_FULL = 1.00
COVERAGE_FACTOR_MID_PCT = 85.00
COVERAGE_FACTOR_MID = 0.90
COVERAGE_FACTOR_LOW = 0.75

# --- administrative fee bands ------------------------------------------------
ADMIN_FEE_BAND_LOW_CEILING = 100_000.00
ADMIN_FEE_BAND_MID_CEILING = 250_000.00
ADMIN_FEE_RATE_LOW = 0.05
ADMIN_FEE_RATE_MID = 0.04
ADMIN_FEE_RATE_HIGH = 0.03

TAX_PAYBACK_FLOOR = 3.00

# --- fund posture ------------------------------------------------------------
FUND_CONSTRAINED_FRACTION = 0.10

# --- attrition ---------------------------------------------------------------
ATTRITION_ALLOWANCE_FRACTION = 0.80
ATTRITION_DAMAGE_RATE = 0.75

# --- relationship score ------------------------------------------------------
SCORE_POINTS_PER_DEFINITE = 12
SCORE_ROOM_NIGHTS_PER_POINT = 500
SCORE_ROOM_NIGHT_CAP = 40
SCORE_PENALTY_PER_LOST = 5
SCORE_MIN = 0
SCORE_MAX = 100
TIER_A_FLOOR = 60
TIER_B_FLOOR = 30
ROLLING_WINDOW_DAYS = 730

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

THRESHOLDS = {
    "MIN_LEAD_DAYS": MIN_LEAD_DAYS,
    "FIRST_HOLD_DAYS": FIRST_HOLD_DAYS,
    "PROMOTION_HOLD_DAYS": PROMOTION_HOLD_DAYS,
    "CHALLENGE_DAYS": CHALLENGE_DAYS,
    "COVERAGE_FLOOR_PCT": COVERAGE_FLOOR_PCT,
    "CUTOFF_TOLERANCE_DAYS": CUTOFF_TOLERANCE_DAYS,
    "MIN_SUPPORT_LETTER_TYPES": MIN_SUPPORT_LETTER_TYPES,
    "MAX_BID_ROUNDS": MAX_BID_ROUNDS,
    "TAX_PAYBACK_FLOOR": TAX_PAYBACK_FLOOR,
}
