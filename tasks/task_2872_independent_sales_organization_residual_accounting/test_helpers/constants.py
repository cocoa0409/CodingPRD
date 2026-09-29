"""Domain thresholds and shared literals stated by the PRD."""

# Vesting schedule (PRD: portfolio vesting).
VESTING_CLIFF_MONTHS = 12
VESTING_STEP_MONTHS = 12
VESTING_STEP_PCT = 25
VESTING_MAX_PCT = 100
VESTING_BUYOUT_MULTIPLE = 24

# Boarding-bonus clawback window.
CLAWBACK_WINDOW_DAYS = 270

# Attrition risk hold.
ATTRITION_HOLD_THRESHOLD_BPS = 2500

# Advance recoupment.
MAX_TOTAL_RECOUPMENT_PCT = 0.5
MAX_RECOUPMENT_PCT = 0.5
TIER_1_CEILING_CENTS = 50000
TIER_2_CEILING_CENTS = 150000
TIER_1_CAP_PCT = 0.25
TIER_2_CAP_PCT = 0.40
TIER_3_CAP_PCT = 0.50
ADVANCE_EXPOSURE_FLOOR_CENTS = 250000
ADVANCE_EXPOSURE_MULTIPLE = 6
MIN_AMORTIZATION_MONTHS = 1
MAX_AMORTIZATION_MONTHS = 60

# Minimum-fee reconciliation.
MINIMUM_SHARE_PCT = 0.5

# Settlement floor.
MIN_PAYOUT_CENTS = 2500

# Hierarchy shape.
MAX_HIERARCHY_DEPTH = 4
MAX_OVERRIDE_LEVELS = 3

# Program economics bounds.
MAX_BUY_RATE_BPS = 500
MAX_ASSESSMENT_BPS = 100

# Pagination defaults.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# The logical clock's value at server startup.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

HOLD_REASON_PORTFOLIO_ATTRITION = "PORTFOLIO_ATTRITION_THRESHOLD"
SYSTEM_USER_ID = "system"

# Canonical processor-file line used repeatedly by the residual scenarios,
# together with the program economics it is priced against.
CANONICAL_PROGRAM = {
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
}

CANONICAL_LINE = {
    "transaction_count": 1240,
    "sales_volume_cents": 4812355,
    "interchange_cents": 92140,
    "assessments_cents": 6255,
    "gross_income_cents": 168430,
}

# Derived figures for the canonical line under the canonical program.
CANONICAL_PROCESSOR_COST_CENTS = 29096
CANONICAL_NET_REVENUE_SPLIT_CENTS = 40939
CANONICAL_GROSS_SPLIT_CENTS = 70035

# The two chargebacks that accompany the canonical July line.
CANONICAL_AGENT_CHARGED_CENTS = 4500
CANONICAL_ISO_ABSORBED_CENTS = 12000

# A thin line used when a statement must land far below the payout floor.
THIN_LINE = {
    "transaction_count": 125,
    "sales_volume_cents": 100000,
    "interchange_cents": 1800,
    "assessments_cents": 130,
    "gross_income_cents": 3200,
}
THIN_LINE_NET_REVENUE_CENTS = 70
