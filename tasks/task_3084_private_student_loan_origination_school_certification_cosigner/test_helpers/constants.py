"""Domain constants — thresholds and published defaults from the PRD."""

# --- published product-policy defaults ---------------------------------------
COSIGNER_RELEASE_MIN_ON_TIME_PAYMENTS = 24
COSIGNER_RELEASE_MIN_CREDIT_SCORE = 660
COSIGNER_RELEASE_MAX_DTI_RATIO = 0.45
AUTODEBIT_RATE_REDUCTION_PCT = 0.25
AUTODEBIT_MIN_PAYMENTS = 24
EXTENDED_TERM_MONTHS = 120
CAPITALIZED_INTEREST_CAP_PCT = 0.10
IN_SCHOOL_MAX_DEFERMENT_MONTHS = 48
REPAYMENT_MAX_DEFERMENT_MONTHS = 24
DELINQUENCY_NOTICE_THRESHOLD_DAYS = 5
ALLOWS_STANDALONE_BORROWER = False

# --- combined credit underwriting -------------------------------------------
COSIGNER_WEIGHT = 0.55
BORROWER_WEIGHT = 0.45
STANDALONE_PENALTY = 25
TIER_A_MIN = 750
TIER_B_MIN = 700
TIER_C_MIN = 650
TIER_D_MIN = 600
MARGIN_A_PCT = 2.75
MARGIN_B_PCT = 3.75
MARGIN_C_PCT = 5.50
MARGIN_D_PCT = 7.25

# --- cosigner backing gate ---------------------------------------------------
COSIGNER_BACKING_CREDIT_MARGIN = 60

# --- repayment / capitalization ---------------------------------------------
MIN_MONTHLY_PAYMENT_CENTS = 5000
APPROVED_AMOUNT_FLOOR_CENTS = 100000
REHABILITATION_PAYMENT_MULTIPLE = 3

# --- delinquency aging -------------------------------------------------------
PERIOD_CLOSE_LAG_DAYS = 5
LATE_MAX_DAYS = 29
DELINQUENT_MAX_DAYS = 119
DEFAULT_MIN_DAYS = 120

# --- cosigner release scoring ------------------------------------------------
CREDIT_COMPONENT_CAP = 300
CREDIT_COMPONENT_FLOOR_SCORE = 550
DTI_COMPONENT_CAP = 250
DTI_COMPONENT_INTERCEPT = 0.60
DTI_COMPONENT_SCALE = 1000
RUN_COMPONENT_CAP = 200
RELEASE_SCORE_MIN = 500

# --- the logical clock -------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- defaults used by the fixtures ------------------------------------------
TEST_DEFAULTS = {
    "BORROWER_SCORE": 700,
    "BORROWER_DTI": 0.24,
    "COSIGNER_SCORE": 760,
    "COSIGNER_DTI": 0.20,
    "REQUESTED_AMOUNT_CENTS": 805000,
    "COST_OF_ATTENDANCE_CENTS": 900000,
    "OTHER_AID_CENTS": 95000,
    "REPAYMENT_TERM_MONTHS": 120,
    "CERTIFIED_AMOUNT_CENTS": 805000,
    "DISBURSEMENT_AMOUNT_CENTS": 805000,
    "PERIOD_PAYMENT_CENTS": 8055,
    "SCHOOL_CAPACITY_CENTS": 100_000_000,
}

# Literal values the default scenario produces, verified against the PRD
# formulas (borrower 700 / cosigner 760 eligible):
#   provisional = max(700, 760) = 760 -> tier A -> 2.75
#   final       = 0.55*760 + 0.45*700 = 733 -> tier B -> 3.75
#   6-month accrual on 805000 at 3.75% = 6 * round(805000 * 0.003125) = 15096
#   STANDARD 120-month annuity on 805000 at 3.75% = 8055
DEFAULT_MARGIN_PCT = MARGIN_B_PCT
DEFAULT_SIX_MONTH_ACCRUAL_CENTS = 15096
DEFAULT_PLAN_PAYMENT_CENTS = 8055