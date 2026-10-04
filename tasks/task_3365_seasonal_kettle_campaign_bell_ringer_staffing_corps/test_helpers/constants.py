"""Domain thresholds and fixtures' default literals.

Every numeric here is stated in the PRD: §2.8 (rounding and precision),
§3.3 (shift scheduling), §3.4 (counting room), §3.6 (eligibility),
§3.7 (corps programs), §3.8 (canteen billing), §3.9 (performance).
"""

# --- Logical clock -------------------------------------------------------
# §2.11: the clock starts at exactly 2026-09-01T00:00:00Z when the server starts.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# --- Counting room (§3.4) ------------------------------------------------
VARIANCE_TOLERANCE_CENTS = 500
ROLL_QUARTER_CENTS = 1000
ROLL_DIME_CENTS = 500
ROLL_NICKEL_CENTS = 200
ROLL_PENNY_CENTS = 50
FEE_MILLS_PER_ROLL = 12
CURRENCY_FEE_PER_MILLE = 5
CHECK_FEE_PER_MILLE = 8
QUARTER_SHARE_PCT = 40
DIME_SHARE_PCT = 30
NICKEL_SHARE_PCT = 20

# --- Seasonal assistance (§3.6) ------------------------------------------
ASSET_DEDUCTION_CENTS = 150000
INCOME_DIVISOR_CENTS = 20000
ELIGIBILITY_THRESHOLD = 65
HOUSEHOLD_SIZE_MIN = 1
HOUSEHOLD_SIZE_MAX = 12

# --- Shift scheduling (§3.3) ---------------------------------------------
MAX_SHIFT_MINUTES = 480
REST_BUFFER_MINUTES = 30
MINOR_CURFEW_HOUR = 20
OVERTIME_AFTER_MINUTES = 420
OVERTIME_MULTIPLIER = 1.5
CHECK_IN_WINDOW_MINUTES = 15

# --- Reliability (§3.3) --------------------------------------------------
BASE_SCORE = 100
COMPLETED_DELTA = 1
LATE_CANCEL_DELTA = -5
NO_SHOW_DELTA = -15
SCORE_FLOOR = 0
SCORE_CEILING = 100
SUSPENSION_THRESHOLD = 60
REINSTATEMENT_SCORE = 60

# --- Location performance (§3.9) -----------------------------------------
MIN_RATED_HOURS = 8
BRONZE_MAX_CENTS_PER_HOUR = 4000
SILVER_MAX_CENTS_PER_HOUR = 8000
GOLD_MAX_CENTS_PER_HOUR = 12000
DEMOTION_INDEX_FLOOR = 2000
UNDERSTAFFED_THRESHOLD_PCT = 80

# --- Digital giving (§3.5) -----------------------------------------------
MAX_DIGITAL_GIFT_CENTS = 500000

# --- Canteen deployment billing (§3.8) -----------------------------------
DAILY_RATE_TYPE_1_CENTS = 95000
DAILY_RATE_TYPE_2_CENTS = 72000
DAILY_RATE_TYPE_3_CENTS = 48000
DAILY_RATE_TYPE_4_CENTS = 30000
DAILY_RATE_TYPE_5_CENTS = 18000
REGULAR_DAY_LIMIT = 14
SURGE_MULTIPLIER = 0.6

# --- Defaults used to build fixtures -------------------------------------
CAMPAIGN_STARTS_ON = "2026-11-01T00:00:00Z"
CAMPAIGN_ENDS_ON = "2026-12-24T23:59:59Z"
PLACEMENT_STARTS_ON = "2026-11-01T00:00:00Z"
PLACEMENT_ENDS_ON = "2026-12-24T00:00:00Z"
INTAKE_OPENS_ON = "2026-10-01T00:00:00Z"
INTAKE_CLOSES_ON = "2026-12-15T23:59:59Z"
DEFAULT_CLOCK = "2026-11-15T00:00:00Z"
DEFAULT_DAILY_REQUIRED_MINUTES = 480
DEFAULT_CAMPAIGN_GOAL_CENTS = 5000000
DEFAULT_LABOR_BUDGET_CENTS = 2000000
