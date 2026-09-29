"""Domain thresholds and numeric constants stated by the PRD.

Every monetary figure here is a whole number of cents (integers), never a
string and never a float, because the PRD carries money in whole cents.
"""

# --- The logical clock -------------------------------------------------------

# The server's logical clock reads exactly this instant at startup.
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# Every fixture in this suite pins the clock to an explicit operating instant
# first, so no evaluation depends on where a previous test left the clock.
DEFAULT_TEST_CLOCK = "2026-08-10T04:00:00Z"

# --- Method labor factors (PRD §3.1) ----------------------------------------

METHOD_LABOR_FACTORS = {
    "SCRATCH": 1.0,
    "PAR_BAKED": 0.6,
    "THAW_AND_SERVE": 0.25,
}

# --- Day-of-week forecast uplift (PRD §3.2) ---------------------------------

DOW_UPLIFT = {
    "MON": 1.00,
    "TUE": 1.00,
    "WED": 1.00,
    "THU": 1.05,
    "FRI": 1.15,
    "SAT": 1.25,
    "SUN": 1.10,
}

# 2026-08-12 is a Wednesday, so its uplift is 1.00 and a forecast line is
# taken exactly as entered.
WEDNESDAY_BUSINESS_DATE = "2026-08-12"
WEDNESDAY_DAY_OF_WEEK = "WED"

# --- Daypart targeting (PRD §3.3) -------------------------------------------

DAYPART_TARGET_OFFSET_HOURS = {"MORNING": 0, "MIDDAY": 5, "EVENING": 10}
DAYPART_RANK = {"MORNING": 1, "MIDDAY": 2, "EVENING": 3}
SLOT_SEARCH_GRID_MINUTES = 5

# --- Markdown window (PRD §3.6) ---------------------------------------------

MARKDOWN_WINDOW_HOURS = 4
DEFAULT_MARKDOWN_PCT = 0.5

# --- Custom cake decoration effort and quoting (PRD §3.7) -------------------

COMPLEXITY_UNITS_PER_TIER = {"SIMPLE": 2, "STANDARD": 4, "PREMIUM": 7}
DECORATION_UNIT_CENTS = 450

RUSH_FLAT_FEE_CENTS = 800
RUSH_LOW_BRACKET_CEILING_CENTS = 5000
RUSH_MID_BRACKET_CEILING_CENTS = 15000
RUSH_MID_BRACKET_RATE = 0.12
RUSH_HIGH_BRACKET_RATE = 0.08

VOLUME_DISCOUNT_HIGH_FLOOR_CENTS = 20000
VOLUME_DISCOUNT_HIGH_RATE = 0.10
VOLUME_DISCOUNT_MID_FLOOR_CENTS = 10000
VOLUME_DISCOUNT_MID_RATE = 0.05

LEAD_BASE_MINUTES = {"SIMPLE": 60, "STANDARD": 120, "PREMIUM": 240}
LEAD_MINUTES_PER_TIER = 30
LEAD_MINUTES_ALLERGEN_FREE = 45

MAX_REVISION_COUNT = 2
MAX_TIER_COUNT = 4

# --- Purchasing (PRD §3.8) --------------------------------------------------

DEFAULT_FREIGHT_SURCHARGE_PCT = 0.05
AUTO_REORDER_TOPUP_MULTIPLIER = 2

# --- Pagination (PRD §2.3) --------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Test defaults ----------------------------------------------------------

TEST_DEFAULTS = {
    "DEPARTMENT_NAME": "Store 41 Bakery",
    "STORE_NUMBER": "0041",
    "SECOND_DEPARTMENT_NAME": "Store 88 Bakery",
    "SECOND_STORE_NUMBER": "0088",
    "SHRINK_BUDGET_PCT": 0.03,
    "LABOR_RATE_CENTS_PER_MINUTE": 40,
    "FREIGHT_SURCHARGE_PCT": 0.05,
    "BUSINESS_DATE": "2026-08-12",
    "LABOR_BUDGET_MINUTES": 600,
    "OVEN_SHIFT_START_UTC": "2026-08-12T04:00:00Z",
    "OVEN_SHIFT_END_UTC": "2026-08-12T20:00:00Z",
}
