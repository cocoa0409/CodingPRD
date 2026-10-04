"""Domain thresholds and shared constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_START = "2026-09-01T00:00:00Z"

# Net worth rule (PRD §3.1).
SMALL_LENDER_FLOOR_CENTS = 50_000_000
STANDARD_FLOOR_CENTS = 100_000_000
SMALL_LENDER_VOLUME_CAP_CENTS = 5_000_000_000
LIQUIDITY_MULTIPLIER = 5
FILING_STALE_MONTHS = 15

# Upfront MIP / refinance credit (PRD §3.3).
UFMIP_RATE_BPS = 175
REFUND_START_BPS = 8000
REFUND_STEP_BPS_PER_MONTH = 200
REFUND_FLOOR_BPS = 1000
REFUND_WINDOW_MONTHS = 36

# Annual MIP and cancellation (PRD §3.3).
VINTAGE_CUTOVER_ISO = "2024-01-01T00:00:00Z"
PRE_ANNUAL_RATE_BPS = 55
POST_RATE_LTV_LE_9000_BPS = 50
POST_RATE_LTV_LE_9500_BPS = 55
POST_RATE_LTV_GT_9500_BPS = 80
PRE_CANCEL_BALANCE_BPS = 7800
PRE_CANCEL_MIN_AGE_MONTHS = 60
POST_CANCEL_MIN_AGE_MONTHS = 132
POST_CANCEL_LTV_GATE_BPS = 9000

# Defect severity scoring (PRD §3.5).
CODE_WEIGHT = {
    "INCOME_MISCALC": 40,
    "APPRAISAL_INFLATED": 35,
    "ASSET_VERIFICATION_MISSING": 20,
    "QC_PLAN_VIOLATION": 15,
    "ELIGIBILITY_CRITERIA_UNMET": 25,
}
PATTERN_MIN_OTHER_REVIEWS = 2
TIER1_MIN_SCORE = 50
TIER2_MIN_SCORE = 25

# Claims (PRD §3.8).
COVERAGE_PCT_BPS = 8500
CWOC_PRINCIPAL_FACTOR_BPS = 9000
CLAIM_DEADLINE_DAYS = 180

# Loan modification restructure (PRD §3.8).
LATE_FEE_BPS = 400
RATE_REDUCTION_BPS = 200
RATE_FLOOR_BPS = 300
MIN_REDUCTION_BPS = 1000

# Loss mitigation waterfall tiers in action_type order (PRD §3.8).
WATERFALL_TIER_OF = {
    "REPAYMENT_PLAN": 1,
    "SPECIAL_FORBEARANCE": 2,
    "LOAN_MODIFICATION": 3,
    "PARTIAL_CLAIM": 4,
    "PRE_FORECLOSURE_SALE": 5,
    "DEED_IN_LIEU": 6,
}
WATERFALL_ORDER = [
    "REPAYMENT_PLAN",
    "SPECIAL_FORBEARANCE",
    "LOAN_MODIFICATION",
    "PARTIAL_CLAIM",
    "PRE_FORECLOSURE_SALE",
    "DEED_IN_LIEU",
]

# Review window (PRD §3.5).
REVIEW_WINDOW_MONTHS = 24

# Appraisal validity window in days (PRD §3.2).
APPRAISAL_VALIDITY_DAYS = 120

# A well-formed UUID that no test ever creates.
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

# Standard audited-filing numbers used by the shared approved-lender fixture:
# adjusted net worth 1,000,000,000; liquidity product 25,000,000,000.
STANDARD_FILING = {
    "fiscal_year_end": "2025-12-31",
    "total_assets_cents": 50_000_000_000,
    "total_liabilities_cents": 49_000_000_000,
    "liquid_assets_cents": 5_000_000_000,
}

# Standard case numbers (LTV 9600 bps).
STANDARD_CASE = {
    "base_loan_amount_cents": 30_000_000,
    "appraised_value_cents": 31_250_000,
    "term_months": 360,
    "note_rate_bps": 700,
    "current_monthly_payment_cents": 200_000,
}
