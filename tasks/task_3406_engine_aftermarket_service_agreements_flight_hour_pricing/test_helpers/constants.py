"""Domain thresholds — numeric constants stated in the PRD.

Every value below is quoted from PRD prose (sections noted per group);
do not change without a matching PRD change.
"""

# PRD §2.4: "Before any client advances it, the logical clock reads exactly
# 2026-09-01T00:00:00Z."
CLOCK_INITIAL_ISO = "2026-09-01T00:00:00Z"

# PRD §2.3 pagination: "defaults to 10, with a minimum of 1 and a maximum of
# 100. The offset parameter ... defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# PRD §2.6 precision: money 2 dp round-half-up; rates and recognition_pct 4 dp.
MONEY_DP = 2
RATE_PRECISION_DP = 4
PCT_PRECISION_DP = 4

# PRD §2.10 utilization band:
# "A ratio strictly below 0.90 prices the period at a band factor of 0.95;
#  a ratio from 0.90 up to and including 1.10 prices at a band factor of 1.00;
#  a ratio strictly above 1.10 prices at a band factor of 1.08."
UTIL_BAND_LOW_THRESHOLD = 0.90
UTIL_BAND_HIGH_THRESHOLD = 1.10
UTIL_BAND_LOW_FACTOR = 0.95
UTIL_BAND_STANDARD_FACTOR = 1.00
UTIL_BAND_HIGH_FACTOR = 1.08

# PRD §3.4: "if there are none, the ratio defaults to exactly 1.00" and the
# look-back window is "the twelve calendar months ending at the statement
# period, inclusive of the statement month".
NO_DATA_RATIO = 1.00
UTILIZATION_WINDOW_MONTHS = 12

# PRD §2.10 / §3.5 / §3.9 severity-adjusted visit cost:
# "a base visit cost of 1,200,000 USD is multiplied by a severity factor ...
#  1.00 for BENIGN, 1.15 for MODERATE, and 1.30 for HARSH."
WORKSCOPE_BASE_COST_USD = 1200000
SEVERITY_COST_FACTOR_BENIGN = 1.00
SEVERITY_COST_FACTOR_MODERATE = 1.15
SEVERITY_COST_FACTOR_HARSH = 1.30
SEVERITY_COST_FACTOR = {
    "BENIGN": SEVERITY_COST_FACTOR_BENIGN,
    "MODERATE": SEVERITY_COST_FACTOR_MODERATE,
    "HARSH": SEVERITY_COST_FACTOR_HARSH,
}

# PRD §3.5 forecast:
# "converts months to days at 30 days per month" / "adds a fixed interval of
# 72 months" / "ties always go to the cycle-based view".
FORECAST_DAYS_PER_MONTH = 30
CALENDAR_INTERVAL_MONTHS = 72

# PRD §3.6 workscope determination:
# "a buffer of 18 months' worth of assumed cycles" and the floor rejects when
# the post-visit interval "is strictly less than 18 months".
MIN_POST_VISIT_INTERVAL_MONTHS = 18

# PRD §3.7 parts sourcing selector:
# "NEW prices at 1.00 of list with a 7-day lead, REPAIRED at 0.70 with a
#  21-day lead, and USM at 0.45 with a 3-day lead" and
# "ties on equal unit cost break by a fixed class priority of NEW, then
#  REPAIRED, then USM".
CLASS_COST_FACTOR_NEW = 1.00
CLASS_COST_FACTOR_REPAIRED = 0.70
CLASS_COST_FACTOR_USM = 0.45
CLASS_COST_FACTOR = {
    "NEW": CLASS_COST_FACTOR_NEW,
    "REPAIRED": CLASS_COST_FACTOR_REPAIRED,
    "USM": CLASS_COST_FACTOR_USM,
}
CLASS_LEAD_DAYS_NEW = 7
CLASS_LEAD_DAYS_REPAIRED = 21
CLASS_LEAD_DAYS_USM = 3
CLASS_LEAD_DAYS = {
    "NEW": CLASS_LEAD_DAYS_NEW,
    "REPAIRED": CLASS_LEAD_DAYS_REPAIRED,
    "USM": CLASS_LEAD_DAYS_USM,
}
CLASS_PRIORITY = ["NEW", "REPAIRED", "USM"]

# PRD §3.8 lease pricing:
# "it is 0 when the operator's credit_rating is A, and a flat 50,000 USD
#  otherwise."
LEASE_DEPOSIT_USD = 50000

# PRD §3.5 shop capacity:
# "if the number of visits already in INDUCTED status whose
#  actual_induction_date equals the current logical-clock date has reached 2,
#  the induction is rejected with ERR_SHOP_CAPACITY_EXCEEDED — at most 2
#  engines can be inducted on a single logical-clock day."
SHOP_INDUCTION_DAILY_CAPACITY = 2

# PRD §3.9 contract accounting:
# "divided by 8,000 — the life-limited-part reset interval in cycles that each
#  full visit restores" / "deflated by the fixed target margin of 0.15" /
# "the margin floor of 0.05".
LLP_RESET_CYCLES = 8000
TARGET_MARGIN_PCT = 0.15
MARGIN_FLOOR_PCT = 0.05
