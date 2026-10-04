"""Domain thresholds and constants for the Career Agency Field Force API.

Values are taken from the published computation rules: the assessment weight
tables and cut scores, the training-allowance percentages, the validation
window and extension limits, the override rates and default cap, the first-year
commission rate, the chargeback bands and their block threshold, the persistency
tier breakpoints, and the interval/reinstatement windows.
"""

# --- Selection assessment: weight tables, formula weights, cut scores ------
COMPONENT_WEIGHT = 0.70
RAW_COMPONENT_WEIGHT = 0.305

PASS_CUT = 8.00
CONDITIONAL_CUT = 5.50

WEIGHTS_V1 = {
    "MARKET_KNOWLEDGE": 0.175,
    "RELATIONSHIP": 0.275,
    "RESILIENCE": 0.25,
    "ETHICS": 0.30,
}
WEIGHTS_V2 = {
    "MARKET_KNOWLEDGE": 0.30,
    "RELATIONSHIP": 0.15,
    "RESILIENCE": 0.20,
    "ETHICS": 0.35,
}
WEIGHT_TABLES = {"V1": WEIGHTS_V1, "V2": WEIGHTS_V2}

COMPETENCY_KEYS = ["MARKET_KNOWLEDGE", "RELATIONSHIP", "RESILIENCE", "ETHICS"]

# --- Training allowance ----------------------------------------------------
PRODUCT_REQUIREMENT_PCT = 0.35
PRODUCTION_DRAW_PCT = 0.25
FLAT_MONTHLY_AMOUNT = 200000
RECRUITER_OVERRIDE_PCT = 0.05

# --- Validation windows ----------------------------------------------------
WINDOW_OPEN_AT_START = True
MAX_EXTENSIONS = 2

# --- Overrides -------------------------------------------------------------
DISTRICT_OVERRIDE_RATE = 0.03
MANAGING_DIRECTOR_OVERRIDE_RATE = 0.02
DEFAULT_OVERRIDE_CAP_CENTS = 300000

# --- Commission allocation -------------------------------------------------
FIRST_YEAR_COMMISSION_RATE = 0.40

# --- Chargeback ------------------------------------------------------------
EARLY_LAPSE_MONTHS = 11
UNEARNED_DENOMINATOR = 24
LATE_LAPSE_RESIDUAL_PCT = 0.50
REINSTATEMENT_WINDOW_DAYS = 90
CHARGEBACK_BLOCK_CENTS = 500000

# --- Persistency -----------------------------------------------------------
TIER_1_MIN = 95.00
TIER_2_MIN = 90.00
TIER_3_MIN = 85.00
TIER_1_RATE = 0.050
TIER_2_RATE = 0.035
TIER_3_RATE = 0.020

# --- Logical clock ---------------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Reusable test defaults ------------------------------------------------
TEST_DEFAULTS = {
    "OFFICE_CODE": "DO-T000",
    "OFFICE_NAME": "Test District",
    "REGION_CODE": "MW",
    "STATE_CODE": "WI",
    "OVERRIDE_RATE_PCT": 0.03,
    "OVERRIDE_CAP_CENTS": 300000,
    "LEGACY_START": "2026-01-01T00:00:00Z",
    "LEGACY_EXPIRY": "2027-12-31T00:00:00Z",
    "PREMIUM_480000": 480000,
    "PREMIUM_400000": 400000,
    "PREMIUM_1200000": 1200000,
    "PREMIUM_1600000": 1600000,
    "REQUIREMENT_300000": 300000,
    "ALLOWANCE_TOTAL_1200000": 1200000,
    "CANDIDATE_SCHEDULED_DATE": "2026-09-02T00:00:00Z",
    "CONTRACT_START_DATE": "2026-01-07T00:00:00Z",
}

# The competency vector used throughout the fixtures: under V2 it yields a
# weighted score of 8.67 (PASS), so the candidate can always advance.
PASSING_COMPETENCIES = {
    "MARKET_KNOWLEDGE": 8,
    "RELATIONSHIP": 8,
    "RESILIENCE": 7,
    "ETHICS": 9,
}