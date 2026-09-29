"""Domain thresholds and pinned numeric constants stated in the PRD.

All monetary amounts are integer counts of whole cents; all rates are in basis
points, where one basis point is one ten-thousandth.
"""

# ─── The logical clock ────────────────────────────────────────────────────────

# At server startup the logical clock reads exactly this instant.
CLOCK_START = "2026-08-01T00:00:00Z"


# ─── Valuation ────────────────────────────────────────────────────────────────

# Statutory floor used as the comparable median when the comparable count is zero.
COMPARABLE_MEDIAN_FLOOR_CENTS = 4500000
# The income-multiple variant applies eighteen percent of trailing annual receipts.
INCOME_MULTIPLE_BPS = 1800

# Scarcity uplift tiers, on four inclusive lower bounds of quota utilization.
SCARCITY_TIERS = (
    (9000, 2500),
    (7500, 1200),
    (5000, 500),
)
SCARCITY_UPLIFT_NONE = 0
# Utilization reported when quota_licenses_total is zero.
UTILIZATION_WHEN_TOTAL_ZERO_BPS = 10000


# ─── Buyer qualification ──────────────────────────────────────────────────────

QUALIFICATION_BASE_SCORE = 100
REVOCATION_PENALTY_PER_COUNT = 25
REVOCATION_PENALTY_COUNT_CAP = 2
FELONY_PENALTY = 30
NO_CITIZENSHIP_PENALTY = 20
NONRESIDENT_PENALTY = 10
FINAL_REVIEW_CUP_PENALTY = 15
FINAL_REVIEW_LANDLORD_PENALTY = 15
QUALIFIED_MIN_SCORE = 70
PROVISIONALLY_QUALIFIED_MIN_SCORE = 50
DISQUALIFYING_REVOCATION_COUNT = 2


# ─── Deposit requirement ──────────────────────────────────────────────────────

CLASS_SURCHARGE_BPS = {
    "CLASS_47_ONSALE_GENERAL": 300,
    "CLASS_21_OFFSALE_GENERAL": 200,
    "CLASS_41_ONSALE_BEER_WINE": 0,
}
SCARCITY_DIVISOR = 5
EFFECTIVE_DEPOSIT_RATE_CAP_BPS = 3500
DEPOSIT_FLOOR_CENTS = 500000
DEPOSIT_CAP_CENTS = 7500000
DEPOSIT_PCT_BPS_MIN = 500
DEPOSIT_PCT_BPS_MAX = 3500


# ─── Transfer application filing fee ──────────────────────────────────────────

FILING_BASE_CENTS = 30000
CLASS_FEE_CENTS = {
    "CLASS_47_ONSALE_GENERAL": 120000,
    "CLASS_21_OFFSALE_GENERAL": 90000,
    "CLASS_41_ONSALE_BEER_WINE": 45000,
}
POSTING_FEE_CENTS = 15000
DEFICIENCY_ROUND_FEE_CENTS = 30000
EXPEDITE_TIER_2_MIN_SUBTOTAL_CENTS = 200000
EXPEDITE_TIER_2_BPS = 800
EXPEDITE_TIER_1_MIN_SUBTOTAL_CENTS = 120000
EXPEDITE_TIER_1_BPS = 500
EXPEDITE_TIER_0_BPS = 200
MAX_DEFICIENCY_ROUNDS = 2


# ─── Commission and disbursement ──────────────────────────────────────────────

DUAL_AGENCY_BUYER_SPLIT_BPS = 4000
DUAL_AGENCY_SELLER_SPLIT_BPS = 6000
COMMISSION_RATE_BPS_MIN = 100
COMMISSION_RATE_BPS_MAX = 1500


# ─── Safekeeping ──────────────────────────────────────────────────────────────

NONUSE_MIN_DAYS = 180
SAFEKEEPING_INITIAL_MAX_MONTHS = 12
SAFEKEEPING_EXTENSION_MAX_MONTHS = 6
SAFEKEEPING_MAX_EXTENSIONS = 2
SAFEKEEPING_BASE_FEE_CENTS = 20000
REQUESTED_MONTHS_MIN = 1
REQUESTED_MONTHS_MAX = 24


# ─── Publication, protest and contingency windows ─────────────────────────────

POSTING_QUIET_BUFFER_DAYS = 30
DEFAULT_POSTING_PERIOD_DAYS = 30
DEFAULT_PROTEST_WINDOW_DAYS = 30
DEFAULT_PROTEST_RESPONSE_DUE_DAYS = 15
DEFAULT_CONTINGENCY_DAYS = 120
CONTINGENCY_DAYS_MIN = 30
CONTINGENCY_DAYS_MAX = 365


# ─── County statutory defaults ────────────────────────────────────────────────

DEFAULT_PERMITTED_ZONING_CODES = ["C1", "C2", "MU1"]
DEFAULT_DISTANCE_MIN_FEET_SCHOOL = 600
DEFAULT_DISTANCE_MIN_FEET_CHURCH = 600
DEFAULT_TRANSFER_FEE_BPS = 150
DEFAULT_VALUATION_BASIS = "COMPARABLE_SALES"


# ─── Miscellaneous input floors ───────────────────────────────────────────────

MIN_ASK_PRICE_CENTS = 100000
MIN_PURCHASE_PRICE_CENTS = 100000
MIN_QUOTA_LICENSES_TOTAL = 1


# ─── Pagination ───────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
