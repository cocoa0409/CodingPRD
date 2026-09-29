"""Domain thresholds and canonical literals drawn from the PRD's calculations.

Money is whole cents. Catalog unit prices are whole micro-dollars
(1 cent = 10000 micro-dollars). Proportions are whole basis points
(10000 basis points is unity).
"""

MICROS_PER_CENT = 10000
BPS_UNITY = 10000

# --- Global defaults ---------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
GREEN_INDEX_DEFAULT_MICROS = 2000000

# --- Pagination --------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- Account -----------------------------------------------------------------
DEFAULT_PRICE_PROTECTION_DAYS = 90
INITIAL_GREEN_PRICE_FACTOR_BPS = 10000
AT_RISK_ESCALATED_SITE_TRIGGER = 2
ALLIED_ATTACHMENT_WINDOW_DAYS = 90

# --- Site planning -----------------------------------------------------------
CUPS_PER_PERSON_PER_DAY = 1.8
BREW_STYLE_FACTORS = {"DRIP": 1.00, "SINGLE_CUP": 1.15, "ESPRESSO": 0.85}
COVER_PERIOD_WEEKS = 2
PER_CUP_UNIT_FACTORS = {
    "COFFEE": 0.09,
    "CREAMER": 0.50,
    "TEA": 0.05,
    "WATER": 0.01,
    "PANTRY": 0.40,
}
REORDER_POINT_BPS = 4000
PEAK_FACTOR = 0.35
TRAILING_WINDOW_DAYS = 28
TRAILING_SAFETY_UPLIFT_BPS = 11000
TRAILING_WEEKS_DIVISOR = 4

# --- Route scheduling --------------------------------------------------------
DEFAULT_TRAVEL_BUFFER_MINUTES = 30
MAX_TRAVEL_BUFFER_MINUTES = 120
MAX_CAPACITY_MINUTES = 960
MAX_PLANNED_MINUTES = 480

# --- Escalation score --------------------------------------------------------
ESCALATION_WEIGHTS = {
    "STOCKOUT": 20.0,
    "BELOW_REORDER": 7.5,
    "OVERDUE_DESCALE": 15.0,
    "MISSED_VISIT": 10.0,
}
ESCALATION_THRESHOLD = 40.0
ESCALATION_SCORE_CAP = 100.0
MISSED_VISIT_WINDOW_DAYS = 28

# --- Shelf ledger ------------------------------------------------------------
COVER_DAYS = 14
SECONDS_PER_DAY = 86400

# --- Maintenance -------------------------------------------------------------
AWAITING_PARTS_CYCLE_CAP = 3
SANITATION_HOLD_DAYS = 1
LOANER_WRITE_OFF_GRACE_DAYS = 30

# --- Compliance and equipment program charges --------------------------------
COMPLIANCE_WINDOW_DAYS = 90
LOAN_MINIMUM_FLOOR_CENTS = 75000
LOAN_SHORTFALL_BPS = 3500
RENTAL_SHORTFALL_BPS = 2500
RENT_PRORATION_DENOMINATOR_DAYS = 30

# --- Unreturned asset pricing ------------------------------------------------
DEPRECIATION_MONTH_DAYS = 30
DEPRECIATION_BPS_PER_MONTH = 150
RESIDUAL_FLOOR_BPS = 3000
RETRIEVAL_TRIP_FEE_CENTS = 7500

# --- Invoice assembly --------------------------------------------------------
ALLIED_DISCOUNT_TIER_HIGH_BPS = 500
ALLIED_DISCOUNT_TIER_MID_BPS = 300
ALLIED_DISCOUNT_TIER_LOW_BPS = 100
ALLIED_DISCOUNT_HIGH_TOTAL_CENTS = 100000
ALLIED_DISCOUNT_MID_TOTAL_CENTS = 50000
ALLIED_CATEGORY_COUNT_TIER = 3
FREIGHT_FREE_THRESHOLD_CENTS = 50000
FREIGHT_FLAT_CENTS = 2500

# --- Green coffee repricing --------------------------------------------------
MOVEMENT_THRESHOLD_BPS = 800
PASS_THROUGH_BPS = 6000
ADJUSTMENT_CAP_BPS = 1500
GREEN_PRICE_FACTOR_FLOOR_BPS = 5000

# --- Canonical test literals -------------------------------------------------
# A Monday, used as the standard clock anchor so MON-route windows are valid.
ANCHOR_MONDAY = "2026-08-03T08:00:00Z"

TEST_DEFAULTS = {
    "ROUTE_NAME": "Downtown Monday Route",
    "ROUTE_SERVICE_DAY": "MON",
    "ROUTE_CAPACITY_MINUTES": 480,
    "ROUTE_TRAVEL_BUFFER_MINUTES": 30,
    "MODEL_CODE": "URN-30",
    "MODEL_BREWER_CLASS": "THERMAL",
    "MODEL_CUPS_PER_HOUR": 30,
    "MODEL_MIN_HEADCOUNT": 1,
    "MODEL_MAX_HEADCOUNT": 250,
    "MODEL_MONTHLY_RENT_CENTS": 4500,
    "MODEL_DESCALE_INTERVAL_DAYS": 90,
    "MODEL_LIST_VALUE_CENTS": 120000,
    "SITE_HEADCOUNT": 40,
    "SITE_DAYS_PER_WEEK": 5,
    "SITE_SERVICE_MINUTES_ESTIMATE": 45,
    "ACCOUNT_LEGAL_NAME": "Northwind Trading Company",
    "GREEN_INDEX_BASELINE_MICROS": 2000000,
}

# Site with headcount 40, five days a week, DRIP brew style:
# forecast 360 cups per week, required peak 26 cups per hour.
EXPECTED_FORECAST_CUPS_PER_WEEK = 360
EXPECTED_REQUIRED_PEAK_CUPS_PER_HOUR = 26

# The FORECAST par rows that plan produces for the canonical catalog at that site.
# Keyed by catalog label; the two pantry products share the PANTRY category and
# therefore share the same per-cup unit factor and the same par arithmetic.
EXPECTED_PAR_ROWS = {
    "COFFEE": {"par_units": 65, "reorder_point_units": 26},
    "CREAMER": {"par_units": 360, "reorder_point_units": 144},
    "TEA": {"par_units": 36, "reorder_point_units": 15},
    "WATER": {"par_units": 8, "reorder_point_units": 4},
    "PANTRY": {"par_units": 288, "reorder_point_units": 116},
    "PANTRY_CUP": {"par_units": 288, "reorder_point_units": 116},
}

# Canonical catalog prices in micro-dollars, keyed by catalog label.
PRODUCT_PRICES_MICROS = {
    "COFFEE": 4500000,
    "CREAMER": 1250000,
    "TEA": 2000000,
    "WATER": 8750000,
    "PANTRY": 25000,
    "PANTRY_CUP": 15000,
}

# The category each catalog label belongs to.
PRODUCT_CATEGORIES = {
    "COFFEE": "COFFEE",
    "CREAMER": "CREAMER",
    "TEA": "TEA",
    "WATER": "WATER",
    "PANTRY": "PANTRY",
    "PANTRY_CUP": "PANTRY",
}
