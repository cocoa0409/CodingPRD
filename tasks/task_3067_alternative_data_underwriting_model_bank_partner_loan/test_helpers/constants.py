"""Domain thresholds and numeric constants from the PRD."""

# Risk scoring
FLOOR_REJECT_SCORE = 300          # clamped risk_score below this auto-declines at submission
CASHFLOW_STRESS_MULTIPLIER = 0.9  # applied to bank_account_* variable contributions only
CASHFLOW_VARIABLE_PREFIX = "bank_account"

# Instant verification thresholds
NSF_INSTANT_FAIL_THRESHOLD = 3    # nsf_count == 3 fails the INCOME instant check
MIN_MONTHS_EMPLOYED = 3           # months_employed == 3 passes the IDENTITY instant check
MIN_BUREAU_SCORE = 500            # bureau_score >= 500 passes the IDENTITY instant check

# Affordability / approved amount
DTI_CAPACITY_RATIO = 0.40                 # standard capacity ratio
DTI_CAPACITY_RATIO_MANUAL_REVIEW = 0.32   # reduced ratio when manual review was exercised
TERM_CAPACITY_MULTIPLIER = 30

# Loan terms
LOAN_TERM_MONTHS = 36

# Late fees
LATE_FEE_RATE = 0.05
LATE_FEE_CAP_CENTS = 1500

# Delinquency / default
DAYS_PER_SERVICING_PERIOD = 30
DEFAULT_DAYS_DELINQUENT = 120

# Disparate impact (four-fifths rule)
FOUR_FIFTHS_THRESHOLD = 0.80

# Performance attestation
EXPECTED_DEFAULT_RATE_BASE_BPS = 500
EXPECTED_DEFAULT_RATE_ADJUST_PER_POINT_BPS = 10
EXPECTED_DEFAULT_RATE_SCORE_REFERENCE = 550

# Pagination
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Logical clock
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "REQUESTED_AMOUNT_CENTS": 5000000,
    "ANNUAL_INCOME_CENTS": 12000000,
    "MONTHLY_DEBT_PAYMENTS_CENTS": 200000,
    "BUREAU_SCORE": 575,
    "APR": 12.0,
}
