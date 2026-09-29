"""Programme constants and canonical fixture literals for the Retailer Installation
Services API.

Every value here is taken from the PRD: the programme thresholds of sections 2.x
and 3.x, and the worked figures the PRD itself pins down.
"""

# --- Logical clock -----------------------------------------------------------
# "On a freshly started server the logical clock reads exactly
# 2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

# --- Money / labour pricing --------------------------------------------------
MIN_LABOR_CHARGE_CENTS = 15000          # programme minimum labour charge
TIER_1_UPPER_UNITS = 200.00             # first 200.00 units at the base rate
TIER_2_UPPER_UNITS = 500.00             # above 200.00 and up to 500.00
TIER_2_RATE_FACTOR = 0.92
TIER_3_RATE_FACTOR = 0.85
SUBFLOOR_MINOR_FACTOR = 0.04
SUBFLOOR_MAJOR_FACTOR = 0.09
OBSTRUCTION_CHARGE_CENTS = 1850
STAIR_FLIGHT_CHARGE_CENTS = 4200

# --- Change-order pricing ----------------------------------------------------
CHANGE_ORDER_ADMIN_FACTOR = 1.06
TRIM_LINEAR_FT_RATE_CENTS = 296
FIXTURE_EACH_RATE_CENTS = 7350
CHANGE_ORDER_MIN_LINES = 1
CHANGE_ORDER_MAX_LINES = 10
CREDIT_CAP_FRACTION = 0.50

# --- Assignment calendar and capacity ---------------------------------------
TRAVEL_BUFFER_MINUTES = 90
MAX_COMMITTED_MINUTES = 4800
MIN_DELIVERY_SLACK_HOURS = 24

# --- Scorecard ---------------------------------------------------------------
BASE_SCORE = 85.00
SCORE_MIN = 0.00
SCORE_MAX = 100.00
ROLLING_WINDOW_DAYS = 90
CSAT_STEP = 5.00
CSAT_NEUTRAL = 3
COMPOSITE_QUALITY_WEIGHT = 0.45
COMPOSITE_TIMELINESS_WEIGHT = 0.30
COMPOSITE_SATISFACTION_WEIGHT = 0.25
REMOVAL_COMPOSITE_MAX = 70.00
PROBATION_COMPOSITE_MAX = 78.00
MIN_EVENTS_FOR_ACTION = 3
REMOVAL_NO_SHOW_COUNT = 3
REMOVAL_SAFETY_COUNT = 2

# Frozen point deltas, keyed by event_type: (quality, timeliness, satisfaction)
EVENT_DELTAS = {
    "ON_TIME_COMPLETION": (2.00, 6.00, 1.00),
    "LATE_COMPLETION": (0.00, -8.00, -3.00),
    "NO_SHOW": (-4.00, -20.00, -10.00),
    "PUNCH_MINOR": (-3.00, 0.00, -1.00),
    "PUNCH_MAJOR": (-8.00, -2.00, -4.00),
    "PUNCH_SAFETY": (-15.00, -3.00, -8.00),
    "WARRANTY_UPHELD": (-10.00, 0.00, -6.00),
}

# Lifetime decay bands: (inclusive upper bound in whole days, weight)
DECAY_BANDS = ((90, 1.00), (270, 0.60), (540, 0.30), (None, 0.10))

# --- Cancellation settlement -------------------------------------------------
LABOR_FORFEIT_PCT = {
    "DRAFT": 0.00,
    "MEASURE_PENDING": 0.00,
    "MEASURED": 0.10,
    "CHANGE_PENDING": 0.10,
    "SCHEDULED": 0.25,
    "IN_PROGRESS": 0.50,
}
RESTOCKING_PCT = {
    "PLANNED": 0.00,
    "IN_TRANSIT": 0.06,
    "DELAYED": 0.06,
    "DELIVERED": 0.12,
    "RETURNED": 0.00,
}
GOODWILL_RETAIN_FACTOR = 0.50
GOODWILL_MIN_PROJECT_COUNT = 3
COOLING_OFF_HOURS = 72
REINSTATE_WINDOW_HOURS = 72

# --- Warranty ----------------------------------------------------------------
WARRANTY_PERIOD_DAYS = 365

# --- Pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- Sentinel identifiers used for not-found probing ------------------------
MISSING_PROJECT_ID = "00000000-0000-4000-8000-000000000999"
MISSING_ASSIGNMENT_PROJECT_ID = "00000000-0000-4000-8000-0000000000a1"
MISSING_ASSIGNMENT_INSTALLER_ID = "00000000-0000-4000-8000-0000000000a2"
MISSING_INSTALLER_ID = "00000000-0000-0000-0000-0000000000ff"

# --- Canonical worked figures the PRD pins ----------------------------------
# 420.00 units, base rate 425, minimum billable 150.00, multiplier 1.15
QUOTED_420_METRO01 = 196673
DEPOSIT_420_METRO01 = 59002
# the same 420.00 units against a multiplier of 1.00
QUOTED_420_METRO02 = 171020
DEPOSIT_420_METRO02 = 51306
