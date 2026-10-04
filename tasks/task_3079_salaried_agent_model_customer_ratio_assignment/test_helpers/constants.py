"""Domain thresholds — numeric constants stated in the PRD.

Values are taken verbatim from the PRD's §2/§3 narrative (band edges, caps,
windows and weights), never re-derived.
"""

# --- Logical clock ----------------------------------------------------------

DEFAULT_LOGICAL_CLOCK = "2026-09-01T00:00:00Z"


# --- Band arithmetic (§2.6) -------------------------------------------------

NEAR_TARGET_BAND_MIN = 0.75
OVER_TARGET_BAND_MIN = 1.00
OVER_TARGET_VETO_CEILING = 1.25
DEFAULT_TARGET_CLIENT_RATIO = 1.0


# --- Region referral programme (§3.1, §3.8) ---------------------------------

DEFAULT_REGION_CAPACITY = 10
DEFAULT_ENROLMENT_IS_REQUIRED = False
REFERRAL_PARTNER_CAPACITY = 3


# --- Listing fees and service commitment (§3.6) -----------------------------

MARGINAL_TIER_BREAKS = [50_000_000, 100_000_000, 200_000_000]
MARGINAL_TIER_RATES = [0.015, 0.0125, 0.010]
LIST_PRICE_MIN_CENTS = 10_000_000
LIST_FEE_RATE_CEILING_PCT = 0.015
FULL_SERVICE_HOURS = 24
LIMITED_SERVICE_HOURS = 48
MLS_ONLY_HOURS = 0
BREACH_REVISION_HOURS = 24
TRAILING_SLICE_BREAKS = [33_333_333, 100_000_000, 200_000_000]
TRAILING_SLICE_HOURS = [0.0147, 0.0113, 0.0091]


# --- Salaried bonus (§3.2) --------------------------------------------------

BONUS_CLOSE_WEIGHT = 0.2
BONUS_CSAT_WEIGHT = 0.15
BONUS_OCCUPANCY_WEIGHT = 0.1
BONUS_PCT_CAP = 0.30
BONUS_MIN_CLOSED_TRANSACTIONS = 3
SATISFACTION_INCLUDED_STATES = ["RESPONDED"]
SATISFACTION_SCORE_MAX = 5.0


# --- Referral fees (§3.8) ---------------------------------------------------

MAX_REFERRAL_FEE_BPS = 2500
REFERRAL_FEE_CAP_BPS = 2500
REFERRAL_FEE_BPS_PER_10K_SALARY_CENTS = 1
SPLIT_25_PARTNER_SHARE = 0.25
SPLIT_50_PARTNER_SHARE = 0.50


# --- Tours (§3.7) -----------------------------------------------------------

ACCESS_CODE_RELEASE_LEAD_MINUTES = 120
NO_SHOW_GRACE_MINUTES = 30
TOUR_BLOCK_WINDOW_MINUTES = 60
TOUR_WINDOW_DAYS = 7
TOUR_WINDOW_HOURS = 36
ASSOCIATE_CAPACITY_LIMIT = 4
TOUR_LOAD_BAND_EDGES = [0, 1, 5]


# --- Transaction satisfaction credit (§3.10) --------------------------------

SATISFACTION_CREDIT = 0.05
SATISFACTION_CREDIT_WINDOW_DAYS = 180


# --- Rounding precision -----------------------------------------------------

MONEY_PRECISION_PLACES = 0
RATIO_PRECISION_PLACES = 4
SCORE_PRECISION_PLACES = 2


# --- Test defaults ----------------------------------------------------------

TEST_DEFAULTS = {
    "REGION_NAME": "Puget Sound",
    "SERVICE_AREA_CODES": ["98101", "98102", "98103"],
    "TRADITIONAL_COMMISSION_PCT": 0.025,
    "TARGET_CLIENT_RATIO": 2.0,
    "REGION_CAPACITY": 10,
    "AGENT_BASE_SALARY_CENTS": 8_000_000,
    "AGENT_BENEFITS_CENTS": 0,
    "AGENT_EXPENSE_ALLOWANCE_CENTS": 0,
    "ASSOCIATE_BASE_SALARY_CENTS": 6_000_000,
    "LIST_PRICE_CENTS": 60_000_000,
    "LIST_FEE_RATE_PCT": 0.0125,
    "REFERRAL_FEE_BPS": 1500,
    "CONTRACT_PRICE_CENTS": 80_000_000,
    "ACCESS_INSTRUCTIONS": "Lockbox 4821 at the side gate",
}

# Common timestamps used by clock-driven setup.
TOUR_SCHEDULED_AT = "2026-09-02T10:00:00Z"
TOUR_CONFIRM_CLOCK = "2026-09-02T08:00:00Z"