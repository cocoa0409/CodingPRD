"""Domain thresholds and term-table constants (PRD §2.4, §2.6, §2.7, §3.2, §3.5, §3.6, §3.7)."""

# --- The logical clock (PRD §2.4) -------------------------------------------
# "Before it is ever set, the logical clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
# Standard "after the application window" instant used across setups.
CLOCK_AFTER_CLOSE_ISO = "2026-10-02T00:00:00Z"

# --- Term table (PRD §2.7) ----------------------------------------------------
TERM_MINUTES = {
    "FULL_TIME": 102000,
    "HALF_TIME": 54000,
    "REDUCED_HALF_TIME": 40500,
    "QUARTER_TIME": 27000,
    "MINIMUM_TIME": 18000,
    "ABBREVIATED_TIME": 6000,
}

AWARD_CENTS = {
    "FULL_TIME": 739500,
    "HALF_TIME": 391500,
    "REDUCED_HALF_TIME": 293625,
    "QUARTER_TIME": 195750,
    "MINIMUM_TIME": 130500,
    "ABBREVIATED_TIME": 43500,
}

ALLOWANCE_TOTAL_CENTS = {
    "FULL_TIME": 2200000,
    "HALF_TIME": 1100000,
    "REDUCED_HALF_TIME": 825000,
    "QUARTER_TIME": 550000,
    "MINIMUM_TIME": 366700,
    "ABBREVIATED_TIME": 122200,
}

# One member-service year is one full-time term (PRD §2.7).
MSY_MINUTES = 102000

# --- Statutory gates ----------------------------------------------------------
# Federal-basis cost-per-MSY cap (PRD §3.2): 2300000.00 cents, equality allowed.
COST_PER_MSY_CAP_CENTS = 2300000

# Match floor: allowable * 25 >= federal * 6 (>= 24%, equality allowed) (PRD §3.2).
MATCH_MIN_NUMERATOR = 6
MATCH_MIN_DENOMINATOR = 25
MATCH_RATE_CASH = 1.00
MATCH_RATE_IN_KIND = 0.80

# Education award proration floor (PRD §3.7): certified * 100 >= 15 * term.
PRORATION_FLOOR_PCT = 15
# Use deadline: issued_at + 7 calendar years (PRD §3.7).
AWARD_USE_DEADLINE_YEARS = 7

# Fundraising cap (PRD §3.5): (fundraising + minutes) * 10 <= certified + minutes.
FUNDRAISING_CAP_PCT = 10

# Living allowance period cap (PRD §3.6): a single payment may not exceed
# 100000 cents; exactly 100000 is allowed.
ALLOWANCE_PERIOD_MAX_CENTS = 100000

# Hour entry range (PRD §3.5): minutes between 1 and 48000.
HOUR_ENTRY_MIN_MINUTES = 1
HOUR_ENTRY_MAX_MINUTES = 48000

# Corrective action window (PRD §3.8): due_days between 14 and 90 inclusive.
DUE_DAYS_MIN = 14
DUE_DAYS_MAX = 90

# Visit spacing (PRD §3.8): at least 30 days away from every other
# SCHEDULED or CONDUCTED visit of the same award; exactly 30 allowed.
VISIT_BUFFER_DAYS = 30

# Minimum member age at service_start_date (PRD §3.4).
MIN_MEMBER_AGE_YEARS = 17

# Slot refill ceiling (PRD §3.3): refill while fill_count < 2.
SLOT_MAX_FILL_COUNT = 2

# Standard enrollment service period used by most setups.
DEFAULT_SERVICE_START = "2026-10-15"
DEFAULT_SERVICE_END = "2027-08-15"
