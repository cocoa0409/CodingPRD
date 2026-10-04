"""Domain thresholds and literal defaults named in the PRD."""

# --- Authorization ---
AUTHORIZATION_VALIDITY_DAYS = 365
AUTHORIZATION_RESOLVE_DAYS = 7

# --- Dispute cycle ---
DISPUTE_RESPONSE_WINDOW_DAYS = 45
DISPUTE_REOPEN_GRACE_DAYS = 14

# --- Disclosure ---
DISCLOSURE_WINDOW_DAYS = 3650

# --- Settlement ---
SETTLEMENT_VOID_GRACE_DAYS = 30

# --- Review windows ---
REVIEW_WINDOW_BUFFER_DAYS = 3

# --- Batch ingestion ---
MAX_BATCH_RECORD_COUNT = 50000

# --- Annualized income ---
WEEKS_PER_YEAR = 52
MAX_HOURS_PER_WEEK = 60
DEFAULT_HOURS_PER_WEEK = 40
PERIODS_PER_YEAR = {"WEEKLY": 52, "BIWEEKLY": 26, "SEMIMONTHLY": 24, "MONTHLY": 12}

# --- Contributor pricing tiers ---
CONTRIBUTOR_TIER1_RATE = 12
CONTRIBUTOR_TIER2_RATE = 10
CONTRIBUTOR_TIER3_RATE = 8
CONTRIBUTOR_TIER2_MIN = 1000
CONTRIBUTOR_TIER3_MIN = 10000

# --- Verification fee ---
VOLUME_STEP1_MIN = 2
VOLUME_STEP2_MIN = 5
TIER_DEPTH_SURCHARGE_CENTS = {
    "EMPLOYMENT_ONLY": 0,
    "EMPLOYMENT_INCOME": 350,
    "FULL_INCOME_HISTORY": 900,
}

# --- Feed currency ---
CADENCE_INTERVAL_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14, "SEMIMONTHLY": 15, "MONTHLY": 30}
FEED_STALLED_MULTIPLIER = 3

# --- Currency score ---
FEED_BASE_WEIGHT = 250
FEED_RECENCY_WEIGHT = 200
FEED_RESPONSIVENESS_WEIGHT = 150
FEED_DECAY_PER_DAY = 3
FEED_SCORE_FLOOR = 0
FEED_SCORE_CEILING = 600
STALL_STRIKE_THRESHOLD = 300

# --- Verifier risk contagion ---
DISPUTE_ESCALATION_PENALTY = 25
FEED_STALL_PENALTY = 40
REVERSAL_PENALTY = 30
VERIFIER_CONTAGION_FACTOR = 1.5
VERIFIER_SCORE_CEILING = 1000
VERIFIER_RESTRICT_SCORE = 100

# --- Tier depth ---
TIER_HISTORY_DEPTH = {
    "EMPLOYMENT_ONLY": 0,
    "EMPLOYMENT_INCOME": 12,
    "FULL_INCOME_HISTORY": 24,
}
ALWAYS_RENDERED = [
    "employer_feed_status",
    "employer_legal_name",
    "hire_date",
    "records_matched_count",
]

# --- Required canonical mapping vocabulary ---
REQUIRED_CANONICAL_FIELDS = [
    "worker_ssn_last4",
    "worker_date_of_birth",
    "hire_date",
    "employment_status",
    "pay_rate",
    "pay_rate_basis",
]

# --- Logical clock ---
DEFAULT_LOGICAL_CLOCK = "2026-09-01T00:00:00Z"

# --- Common test literals ---
DEFAULTS = {
    "LEGAL_NAME": "Northwind Logistics",
    "FEIN": "123456789",
    "EMPLOYER_TYPE": "PRIVATE",
    "PAYROLL_FREQUENCY": "MONTHLY",
    "BATCH_RECORD_COUNT": 900,
    "PAY_PERIOD_END": "2026-05-31T00:00:00Z",
    # A pay period close enough to the default logical clock that the feed reads
    # CURRENT with no clock manipulation. Used as the fixture default so that
    # currency-dependent preconditions hold out of the box.
    "DEFAULT_FEED_PERIOD_END": "2026-08-31T00:00:00Z",
    "PAY_PERIOD_END_AUG": "2026-08-31T00:00:00Z",
    "WORKER_NAME": "Dana Reyes",
    "WORKER_SSN_LAST4": "4417",
    "WORKER_DOB": "1988-03-14",
    "HIRE_DATE": "2023-01-15T00:00:00Z",
    "PAY_RATE_CENTS": 520000,
    "PAY_RATE_BASIS": "MONTHLY",
    "STANDARD_HOURS_PER_WEEK": 40,
    "PRODUCT_CODE": "MORTGAGE-I12",
    "PRODUCT_TIER": "EMPLOYMENT_INCOME",
    "PRODUCT_REQUESTING_CLASS": "MORTGAGE",
    "PRODUCT_BASE_FEE_CENTS": 1500,
    "PRODUCT_HISTORY_MONTHS": 12,
    "VERIFIER_NAME": "Meridian Home Lending",
    "VERIFIER_CLASS": "MORTGAGE_LENDER",
    "VERIFIER_PURPOSE": "MORTGAGE_CREDIT_DECISION",
    "VERIFIER_ESCROW_CENTS": 6000,
    "COMPLETE_COLUMN_MAP": {
        "W_LAST4": "worker_ssn_last4",
        "W_DOB": "worker_date_of_birth",
        "HIRE": "hire_date",
        "STATUS": "employment_status",
        "RATE": "pay_rate",
        "BASIS": "pay_rate_basis",
    },
}