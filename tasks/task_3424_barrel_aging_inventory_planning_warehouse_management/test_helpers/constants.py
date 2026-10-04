"""Domain constants — every contract value below is stated in PRD prose.

Contract constants (PRD citations inline). Fixture-convention timestamps and
payload defaults are kept in TEST_DEFAULTS, clearly separated, so no test
should mistake them for contract values.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "Before any clock call the server's clock reads exactly 2026-09-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Uniform calendar (PRD §2.4) ----------------------------------------------
# "every month is 30 days and every year is 365 days"
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365

# --- Statutory evaporation rate table (PRD §3.3) -------------------------------
# "a base rate of one percent (0.01) per block"
BASE_QUARTERLY_RATE = 0.01
# "divides the time since fill into consecutive ninety-day blocks"
STATUTORY_BLOCK_DAYS = 90
# WINTER 0.7 / SPRING 1.0 / SUMMER 1.5 / AUTUMN 1.0 (PRD §3.3 season table)
SEASON_MULTIPLIERS = {"WINTER": 0.7, "SPRING": 1.0, "SUMMER": 1.5, "AUTUMN": 1.0}
# "1.2 under two years, 1.0 at two years or more but under six, and 0.8 at six
#  years or more"
AGE_MULTIPLIER_UNDER_2Y = 1.2
AGE_MULTIPLIER_2Y_TO_6Y = 1.0
AGE_MULTIPLIER_6Y_PLUS = 0.8
# "when the barrel's seasoning_months is at least eighteen, the result is
#  further multiplied by 0.95"
SEASONED_WOOD_THRESHOLD_MONTHS = 18
SEASONED_WOOD_DISCOUNT = 0.95
# "the final rate is capped at 0.05"
STATUTORY_RATE_CAP = 0.05

# --- Heat factor (PRD §3.1) ----------------------------------------------------
# "one plus 0.05 multiplied by the slot's floor_index minus one ... exactly
#  1.00 on the ground floor, 1.05 on the second floor, 1.10 on the third"
HEAT_FACTOR_BASE = 1.00
HEAT_FACTOR_PER_FLOOR = 0.05
HEAT_FACTOR_FLOOR_1 = 1.00
HEAT_FACTOR_FLOOR_2 = 1.05
HEAT_FACTOR_FLOOR_3 = 1.10

# --- Sampling buffer (PRD §3.3) -------------------------------------------------
# "a QUALITY_SAMPLE recorded fewer than thirty days after the same barrel's
#  previous QUALITY_SAMPLE is rejected ... exactly thirty days is allowed"
SAMPLE_BUFFER_DAYS = 30

# --- Input ranges (PRD §2.10 gate 3, §3.2, §3.3) ---------------------------------
CHAR_LEVEL_MIN = 1
CHAR_LEVEL_MAX = 4
QUALITY_SCORE_MIN = 0
QUALITY_SCORE_MAX = 100

# --- Pagination (PRD §2.3) --------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

# --- Volume precision (PRD §2.6) ----------------------------------------------------
VOLUME_DECIMAL_PLACES = 2

# --- Fixture conventions (NOT contract values) ---------------------------------------
# The standard test chain: approve at the default clock, then commission once
# a 24-month (720-day) construction lag has fully elapsed:
# 2026-09-01 + 720 days == 2028-08-21. Barrels are conventionally filled at
# 2028-09-01. Both timestamps are derivable from PRD §2.4 calendar arithmetic
# applied to the fixture lag; they pin no PRD rule by themselves.
STANDARD_CONSTRUCTION_LAG_MONTHS = 24
STANDARD_COMMISSION_ISO = "2028-08-21T00:00:00Z"
STANDARD_FILL_ISO = "2028-09-01T00:00:00Z"
# Conventional scheduled bottling date for blend-batch fixtures: a barrel
# filled at STANDARD_FILL_ISO is exactly 2 x 365 days old then.
STANDARD_BOTTLING_ISO = "2030-09-01T00:00:00Z"

TEST_DEFAULTS = {
    # Expansion project payload defaults
    "PROJECT_NAME": "Test Project",
    "REGION_CODE": "KY",
    "FLOORS": 1,
    "ROWS_PER_FLOOR": 1,
    "POSITIONS_PER_ROW": 1,
    "CONSTRUCTION_LAG_MONTHS": STANDARD_CONSTRUCTION_LAG_MONTHS,
    "PLANNED_ANNUAL_DISTILLATION_LITERS": 50000,
    # Barrel payload defaults
    "WOOD_ORIGIN": "AMERICAN_WHITE_OAK",
    "SEASONING_MONTHS": 12,
    "CHAR_LEVEL": 3,
    "SPIRIT_TYPE": "BOURBON",
    "FILL_PROOF": 125.0,
    "FILL_VOLUME_LITERS": 200.0,
    "MIN_MATURATION_MONTHS": 48,
    # Label payload defaults
    "LABEL_NAME": "Test Label",
    "AGE_STATEMENT_YEARS": 1,
    # Program payload defaults
    "PROGRAM_NAME": "Test Program",
    "MIN_QUALITY_SCORE": 0,
    "REQUIRED_BARREL_COUNT": 1,
    "RESERVATION_WINDOW_DAYS": 45,
    # Assessment draw default
    "SAMPLE_DRAW_LITERS": 1.0,
}
