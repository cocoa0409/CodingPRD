"""Domain thresholds and rates named by the contract.

Privacy and sizing thresholds, credit costs, activation rates, penalties, and
the fixed logical-clock default - every magic number a test needs lives here so
assertions read in the contract's own vocabulary.
"""

# Privacy and sizing thresholds (PRD privacy posture).
MIN_CELL_SIZE = 20
MIN_SEGMENT_SIZE = 25

# Report credit costs by report type.
CREDIT_COST_CATEGORY = 1
CREDIT_COST_BRAND_OWN = 2
CREDIT_COST_COMPETITOR_BLIND = 3

# Activation reach-and-fee rates.
RATE_CENTS_PER_HOUSEHOLD = 2.5
REACH_RATE_COUPON = 0.8
REACH_RATE_RETAIL_MEDIA = 0.5
CHANNEL_MULTIPLIER_COUPON = 1.0
CHANNEL_MULTIPLIER_RETAIL_MEDIA = 1.3

# Measurement window for segment activations (days).
MEASUREMENT_WINDOW_DAYS = 28

# Compliance scoring.
COMPLIANCE_SCORE_INITIAL = 1000
LATE_SUBMISSION_PENALTY = 10
MISSED_DELIVERABLE_PENALTY = 25
COMPLIANCE_SCORE_FLOOR = 0

# Clean-room query costing.
MAX_QUERY_COST = 100
QUERY_COST_MINIMUM = 1
ROWS_PER_UNIT = 1000
JOIN_FACTOR_BASE = 1.0
JOIN_FACTOR_STEP = 0.25
TIER_MULTIPLIER_CATEGORY = 1.0
TIER_MULTIPLIER_BRAND = 1.25
TIER_MULTIPLIER_PORTFOLIO = 1.5

# Incrementality lift bias correction weight.
COVARIATE_WEIGHT = 0.5

# Line-review timing.
CYCLE_OPEN_LEAD_DAYS = 14
CYCLE_GAP_MIN_DAYS = 7

# The fixed logical-clock default before any clock-setting call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Reusable request-body defaults.
TEST_DEFAULTS = {
    "REGION": "NW",
    "REPORT_CREDIT_ALLOWANCE": 10,
    "ACTIVATION_BUDGET_CENTS": 100000,
    "QUERY_BUDGET_TOTAL": 100,
    "CATEGORY_CODE": "SNACKS",
    "BRAND_CODES": ["ACME"],
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-31",
}
