"""Domain thresholds and pinned literal values for the heavy civil bidding API.

Every numeric literal used by a test fixture lives here so that tests pin the
value explicitly instead of relying on any server-side default.
"""

# --- Logical clock -----------------------------------------------------------

#: The server's startup default logical time; time advances only through the
#: administrative clock-advance endpoint.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

#: Deadline used by nearly every fixture project (strictly after the start).
DEFAULT_BID_DEADLINE_AT = "2026-12-01T00:00:00Z"

#: A measurement date that falls after bid opening.
DEFAULT_MEASURED_AT = "2026-12-02T00:00:00Z"

# --- Quantity variance bands -------------------------------------------------

OVERRUN_THRESHOLD_PCT = 15.0
UNDERRUN_THRESHOLD_PCT = 15.0

#: Strict boundaries: a variance exactly equal to the band does not trigger.
OVERRUN_BOUNDARY = "strict >"
UNDERRUN_BOUNDARY = "strict <"

UPLIFT_PER_EV_POINT_CENTS = 200
UPLIFT_CAP_EV = 300

# --- Unbalanced bid bands ----------------------------------------------------

BAND_1_RATIO_MAX_EXCLUSIVE = 0.80
BAND_2_RATIO_MAX_EXCLUSIVE = 1.20
BAND_3_RATIO_MAX_EXCLUSIVE = 2.00
MULTIPLIER_BAND_1 = 1.00
MULTIPLIER_BAND_2 = 1.00
MULTIPLIER_BAND_3 = 1.005
MULTIPLIER_BAND_4 = 1.015

# --- Retention ---------------------------------------------------------------

RELEASE_POINTS = 2
ANNUAL_PACE_CENTS = 4_000_000_000
MONTHLY_PACE_CENTS = 333_333_333
#: strict >= : gross payable exactly at the pace releases retention entirely.
PACE_BOUNDARY = "strict >="

# --- Bond statutory requirement tiers ---------------------------------------

TIER_1_MAX_CENTS = 1_000_000
TIER_2_MAX_CENTS = 5_000_000
TIER_3_MAX_CENTS = 10_000_000
TIER_1_PCT = 0.50
TIER_2_PCT = 0.75
TIER_3_PCT = 1.00
TIER_4_PCT = 1.25
PAYMENT_BOND_PCT = 1.00
OTHER_BOND_PCT = 0.10

# --- Notice period -----------------------------------------------------------

NOTICE_LIMIT_DAYS = 30
#: strict > : exactly 30 days elapsed is still a timely notice.
NOTICE_BOUNDARY = "strict >"

# --- Crew productivity -------------------------------------------------------

HOURS_PER_DAY = 8

# --- DBE participation -------------------------------------------------------

EMPTY_DENOMINATOR_RESULT = 0
DBE_PRECISION_DECIMALS = 2

# --- Pagination --------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Declared creation defaults ---------------------------------------------

DEFAULT_CONTRACT_TYPE = "UNIT_PRICE"
DEFAULT_RETENTION_RATE_PCT = 5.0
DEFAULT_ADVERTISED_DBE_GOAL_PCT = 0.0
DEFAULT_MAINTAIN_BOND_HORIZON_DAYS = 30
DEFAULT_VERSION_ROUND = 1

# --- Reusable fixture values -------------------------------------------------

#: The crew-productivity sheet used across fixtures:
#: crew_day_cents = 1_200_000 + 800_000 = 2_000_000 over 1_000 units -> 2_000 c/unit.
CREW_DAY_LABOR_CENTS = 1_200_000
CREW_DAY_EQUIPMENT_CENTS = 800_000
DAILY_PRODUCTIVITY_UNITS = 1_000
BALANCED_UNIT_PRICE_CENTS = 2_000

#: Surety endowments used by fixtures.
SURETY_AGGREGATE_CAPACITY_CENTS = 200_000_000
SURETY_SINGLE_JOB_LIMIT_CENTS = 150_000_000
SURETY_NAME = "Pacific Surety Co"

#: Performance bond face amount used by fixtures.
PERFORMANCE_BOND_AMOUNT_CENTS = 12_000_000
BOND_EFFECTIVE_FROM = "2026-09-01T00:00:00Z"
BOND_EFFECTIVE_TO = "2027-09-01T00:00:00Z"

#: Quote window used by fixtures.
QUOTE_WINDOW_START = "2026-11-01T00:00:00Z"
QUOTE_WINDOW_END = "2026-12-01T00:00:00Z"

#: A structurally valid UUID that no resource is ever allocated.
NON_EXISTENT_PROJECT_ID = "00000000-0000-4000-8000-0000000000ff"
NON_EXISTENT_RECONCILIATION_ID = "00000000-0000-4000-8000-000000000000"
