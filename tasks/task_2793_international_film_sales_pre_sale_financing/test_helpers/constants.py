"""Domain constants taken from the PRD narrative.

Everything here is a literal the PRD states in prose: the fixed startup instant
of the logical clock, the money/rate precisions, the named thresholds of the
pricing, commission, waterfall, advance, occupancy and deliverable rules, and
the canonical figures the suite reuses so that every expected value in a test is
a pre-computed literal rather than a re-implementation of the formula.
"""

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
# "Before any call to this endpoint the logical clock reads exactly
# 2026-08-01T00:00:00Z - the fixed startup default".
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Response envelope / pagination
# --------------------------------------------------------------------------
REQUEST_ID_PREFIX = "req_"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
PAGINATION_META_KEYS = ("total_count", "has_more", "limit", "offset")
LIST_ALL = {"limit": 100, "offset": 0}

# --------------------------------------------------------------------------
# Money and precision
# --------------------------------------------------------------------------
MONEY_DP = 2          # every *_usd amount
RATE_DP = 6           # commission rate, lender discount factor
PCT_DP = 4            # milestone_pct_total, pct_of_mg
MILESTONE_PCT_TOTAL_REQUIRED = 1.0000

# --------------------------------------------------------------------------
# Entities that carry no updated_at / version (common_fields false)
# --------------------------------------------------------------------------
VERSIONLESS_ENTITIES = ("Territory", "ComparableTitle", "DistributionRun")

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
GENRES = ("ACTION", "DRAMA", "COMEDY", "THRILLER", "DOCUMENTARY")
COMPLETION_STATUSES = ("SCRIPT", "IN_PRODUCTION", "POST", "DELIVERED")
REGIONS = ("EMEA", "APAC", "LATAM", "NORTH_AMERICA")
FILM_SALES_STATUSES = ("DEVELOPMENT", "PACKAGING", "IN_MARKET", "SOLD_OUT", "WRAPPED")
AGREEMENT_STATUSES = ("DRAFT", "EXECUTED", "TERMINATED", "EXPIRED")
CREDIT_RATINGS = ("AAA", "AA", "A", "BBB", "SPECULATIVE")
INVESTMENT_GRADE_RATINGS = ("AAA", "AA", "A")
BUYER_STATUSES = ("ACTIVE", "WATCHLIST", "BLOCKED")
VALUATION_METHODS = ("COMPARABLE_WEIGHTED", "CAST_ADJUSTED")
VALUATION_STATUSES = ("DRAFT", "PUBLISHED", "LICENSED", "STALE")
MARKET_STATUSES = ("PLANNED", "OPEN", "CLOSED")
SLOT_TYPES = ("BUYER_SCREENING", "PRESS", "MARKET_PREMIERE")
SLOT_STATUSES = ("HELD", "CONFIRMED", "CANCELLED")
MEETING_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
MEETING_OUTCOMES = ("PASS", "INTERESTED", "OFFER_REQUESTED")
LIVE_MEETING_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW")
NEGOTIATION_STATUSES = (
    "OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED", "LAPSED", "REVERTED",
)
LIVE_NEGOTIATION_STATUSES = ("OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED")
DELIVERY_STATUSES = ("PENDING", "SUBMITTED", "ACCEPTED", "REJECTED", "CURED")
COLLECTION_STATUSES = ("UNPAID", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF")
MILESTONE_STATUSES = ("SCHEDULED", "INVOICED", "RECEIVED", "WRITTEN_OFF")
MILESTONE_LABELS = ("ON_SIGNATURE", "ON_DELIVERY", "ON_RELEASE", "ON_TERM_END")
PACKAGE_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED", "REJECTED_FINAL")
QC_RESULTS = ("PENDING", "PASS", "FAIL")
REJECTION_REASONS = (
    "TECHNICAL_INCOMPLETE", "LEGAL_INCOMPLETE", "QC_FAIL", "LATE_DELIVERY",
)
FACILITY_STATUSES = (
    "PROPOSED", "APPROVED", "DRAWN", "MARGIN_CALL", "REPAID", "DEFAULTED",
)
ACCOUNT_STATUSES = ("OPEN", "LOCKED", "CLOSED")
TIER_TYPES = (
    "COLLECTION_FEE", "SALES_COMMISSION", "SALES_EXPENSES", "BANK_DEBT",
    "EQUITY_RECOUPMENT", "DEFERMENT", "PARTICIPATION",
)
TIER_STATUSES = ("ACTIVE", "SUSPENDED", "SATISFIED")
# Tier types whose cap_usd the service writes rather than the operator.
SERVICE_CAPPED_TIER_TYPES = ("SALES_COMMISSION", "SALES_EXPENSES", "BANK_DEBT")

# --------------------------------------------------------------------------
# Territory valuation
# --------------------------------------------------------------------------
MIN_COMP_SAMPLE = 3
COMP_LOOKBACK_YEARS = 7
COMP_LOOKBACK_EDGE_YEAR = 2019      # year(2026-08-01) - 7
COMP_LOOKBACK_STALE_YEAR = 2018     # one year outside the inclusive edge
ASK_MULTIPLIER = 1.25
FLOOR_MULTIPLIER = 0.70
CAST_MULTIPLIER_TOP = 1.40          # principal_cast_score >= 85
CAST_MULTIPLIER_HIGH = 1.20         # 70 <= score < 85
CAST_MULTIPLIER_MID = 1.00          # 50 <= score < 70
CAST_MULTIPLIER_LOW = 0.80          # score < 50
COMPARABLE_WEIGHTED_MULTIPLIER = 1.00
MIN_MARKET_TIER = 1
MAX_MARKET_TIER = 3
MIN_BASE_VALUE_INDEX = 0.10
MAX_BASE_VALUE_INDEX = 2.00

# --------------------------------------------------------------------------
# Agency agreement
# --------------------------------------------------------------------------
MIN_TERM_MONTHS = 6
MAX_COMMISSION_PCT = 0.25
EXPENSE_TOLERANCE_MULTIPLIER = 2.00

# --------------------------------------------------------------------------
# Commission accrual bands
# --------------------------------------------------------------------------
COMMISSION_TIER1_BREAK = 1000000.00
COMMISSION_TIER2_BREAK = 3000000.00
COMMISSION_TIER2_FACTOR = 0.75
COMMISSION_TIER3_FACTOR = 0.50

# --------------------------------------------------------------------------
# Buyer credit gates
# --------------------------------------------------------------------------
NET_EXECUTION_HEADROOM = 1.50
MIN_LICENSE_TERM_MONTHS = 12
MIN_HOLDBACK_DAYS = 0
MAX_HOLDBACK_DAYS = 720
MAX_NEGOTIATION_ROUNDS = 4

# --------------------------------------------------------------------------
# Market occupancy
# --------------------------------------------------------------------------
TURNAROUND_MINUTES = 30
MEETING_MINUTES_CAP = 240

# --------------------------------------------------------------------------
# Deliverables
# --------------------------------------------------------------------------
MIN_TECHNICAL_ITEMS = 14
MIN_LEGAL_ITEMS = 6
MAX_REVISION_ROUNDS = 2
CURE_WINDOW_DAYS = 30
ON_RELEASE_PUSH_DAYS = 30

# --------------------------------------------------------------------------
# Lender advance
# --------------------------------------------------------------------------
DISCOUNT_DAY_BASIS = 365
UNBONDED_HAIRCUT = 0.50
MAX_DISCOUNT_RATE_PCT = 0.30
MAX_ADVANCE_RATE_PCT = 1.00

# ==========================================================================
# Canonical slate figures reused across the suite
# ==========================================================================
FILM_TITLE = "Northern Lights"
FILM_GENRE = "ACTION"
FILM_BUDGET = 24000000.00
FILM_CAST_SCORE = 88
FILM_DELIVERY_DATE = "2027-02-28T00:00:00Z"
FILM_RELEASE_DATE = "2027-04-15T00:00:00Z"

TERRITORY_DE_CODE = "DE"
TERRITORY_DE_INDEX = 1.20
TERRITORY_FR_CODE = "FR"
TERRITORY_FR_INDEX = 1.00

# Three verified ACTION comps in DE: 800000 / 1000000 / 1200000 -> median 1000000
COMP_FEES_DE = (800000.00, 1000000.00, 1200000.00)
COMP_MEDIAN_DE = 1000000.00

# CAST_ADJUSTED on DE: 1000000 * 1.20 * 1.40
CA_ESTIMATE_DE = 1680000.00
CA_ASK_DE = 2100000.00
CA_FLOOR_DE = 1176000.00
# COMPARABLE_WEIGHTED on DE: 1000000 * 1.20 * 1.00
CW_ESTIMATE_DE = 1200000.00
CW_ASK_DE = 1500000.00
CW_FLOOR_DE = 840000.00

AGREEMENT_COMMISSION_PCT = 0.10
AGREEMENT_EXPENSE_CAP = 75000.00
AGREEMENT_TERM_MONTHS = 24
AGREEMENT_TERM_START = "2026-08-01T00:00:00Z"
AGREEMENT_TERM_END = "2028-08-01T00:00:00Z"

BUYER_NAME = "Rhein Films"
BUYER_RATING = "AAA"
BUYER_EXPOSURE_LIMIT = 3000000.00
BUYER_ALT_NAME = "Nordic Media"

CONTRACT_MG = 2000000.00
CONTRACT_TERM_MONTHS = 24
CONTRACT_HOLDBACK_DAYS = 60
CONTRACT_LICENSE_END = "2028-08-01T00:00:00Z"      # 2026-08-01 + 24 months
CONTRACT_HOLDBACK_RELEASE = "2027-06-14T00:00:00Z"  # 2027-04-15 + 60 days

# Four-line milestone schedule 0.45 / 0.20 / 0.10 / 0.25 against MG 2000000.00
MILESTONE_SCHEDULE = (
    ("ON_SIGNATURE", 0.45, "2026-09-01T00:00:00Z", 900000.00),
    ("ON_DELIVERY", 0.20, "2027-06-15T00:00:00Z", 400000.00),
    ("ON_RELEASE", 0.10, "2027-07-15T00:00:00Z", 200000.00),
    ("ON_TERM_END", 0.25, "2028-08-01T00:00:00Z", 500000.00),
)

ACCOUNT_BANK_NAME = "Fiduciary Trust"
ACCOUNT_REFERENCE = "CAM-2793"

LENDER_NAME = "Comerica Entertainment"
FACILITY_DISCOUNT_RATE = 0.08
FACILITY_ADVANCE_RATE = 0.80
FACILITY_CAP = 1000000.00
BOND_PROVIDER = "UniCredit Bond"
BOND_AMOUNT = 24000000.00

# Collateral on the canonical contract at clock 2026-08-01 with the latest
# unpaid milestone due 2028-08-01 (731 whole days):
#   factor = round(1 - 0.08 * 731 / 365, 6) = 0.839781
#   value  = round(2000000.00 * 0.80 * 0.839781, 2)
FACILITY_DISCOUNT_FACTOR = 0.839781
FACILITY_COLLATERAL = 1343649.60
FACILITY_ADVANCE_UNBONDED = 500000.00
FACILITY_ADVANCE_BONDED = 1000000.00
# Second facility: discount 0.10, advance 0.60, cap 2000000.00
FACILITY2_DISCOUNT_FACTOR = 0.799726
FACILITY2_COLLATERAL = 959671.20
TENOR_DAYS = 731

MARKET_NAME = "AFM 2026"
MARKET_CITY = "Los Angeles"
MARKET_START = "2026-11-05T00:00:00Z"
MARKET_END = "2026-11-11T23:59:59Z"
MARKET_ROOMS = 4
MARKET_TABLES = 10
