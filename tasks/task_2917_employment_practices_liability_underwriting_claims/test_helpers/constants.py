"""Domain constants: route prefix, logical-clock epoch, pagination and calculation tables."""

API_PREFIX = "/epli"

# --- Logical clock --------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# --- Pagination ----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Timestamps ----------------------------------------------------------
TIMESTAMP_FRACTIONAL_DIGITS = 3

# --- Hazard load ---------------------------------------------------------
HAZARD_TIER_LOAD_PCT = {"T1": 0.025, "T2": 0.070, "T3": 0.135, "T4": 0.205}
MULTI_JURISDICTION_SPREAD_PCT = 0.010
HAZARD_LOAD_CAP_PCT = 0.30

# --- Risk-management credit ---------------------------------------------
RISK_CREDIT_CAP_PCT = 0.15

# --- Exposure score ------------------------------------------------------
HEADCOUNT_BAND_POINTS = ((1, 50, 8.00), (51, 250, 16.00), (251, 1000, 26.00), (1001, None, 34.00))
HAZARD_TIER_POINTS = {"T1": 5.00, "T2": 12.00, "T3": 20.00, "T4": 28.00}
MULTI_JURISDICTION_POINTS_EACH = 2.00
MULTI_JURISDICTION_POINTS_CAP = 8.00
TURNOVER_POINTS_FACTOR = 0.80
TURNOVER_POINTS_CAP = 30.00
SERVICE_SCORE_CREDIT_POINTS = {
    "HOTLINE_SUBSCRIPTION": 6.00,
    "HANDBOOK_REVIEW": 4.00,
    "MANAGER_TRAINING": 3.00,
}
EXPOSURE_SCORE_MIN = 0.00
EXPOSURE_SCORE_MAX = 100.00
REFERRAL_THRESHOLD = 72.00

# --- Premium -------------------------------------------------------------
HEADCOUNT_PREMIUM_FACTORS = ((1, 50, 1.000), (51, 250, 0.925), (251, 1000, 0.855), (1001, None, 0.785))
TURNOVER_LOAD_BANDS = ((0.00, 9.99, 0.00), (10.00, 19.99, 0.06), (20.00, 34.99, 0.14), (35.00, None, 0.25))
LIMIT_FACTOR_BASE_CENTS = 100000000
LIMIT_FACTOR_STEP = 0.10
RETENTION_CREDIT_BANDS = ((0, 2499999, 0.00), (2500000, 9999999, 0.05), (10000000, None, 0.11))

# --- Blended rate --------------------------------------------------------
BLENDED_PARTNER_WEIGHT = 0.35
BLENDED_ASSOCIATE_WEIGHT = 0.50
BLENDED_PARALEGAL_WEIGHT = 0.15

# --- Retention mechanics -------------------------------------------------
WAGE_HOUR_RETENTION_MULTIPLIER = 1.50
THIRD_PARTY_RETENTION_MULTIPLIER = 1.25
PRE_SUIT_CREDIT_CEILING_CENTS = 750000
PRE_SUIT_CREDIT_RATE = 0.30

# --- Invoice guideline audit --------------------------------------------
PARTNER_RATE_CAP_CENTS_PER_HOUR = 75000
ASSOCIATE_RATE_CAP_CENTS_PER_HOUR = 45000
BLOCK_BILLING_REDUCTION_RATE = 0.20
EXPENSE_ALLOWANCE_RATE = 0.08

# --- Panel tier ordinal --------------------------------------------------
PANEL_TIER_ORDINAL = {"LOCAL": 0, "REGIONAL": 1, "NATIONAL": 2}

SECONDS_PER_DAY = 86400
