"""Domain thresholds and defaults from PRD sections 3.1-3.10."""

# Ad slot split / resplit (PRD section 3.4)
STANDING_PENALTY_BPS = 500

# Subscription payout (PRD section 3.7)
PROCESSING_FEE_PER_CHARGE_CENTS = 55
STANDARD_FEE_BPS = 2000
PREMIER_FEE_BPS = 1500
PREMIER_THRESHOLD_CENTS = 10000000

# Campaign fiscal gate (PRD section 3.5)
CAMPAIGN_CREDIT_LIMIT_CENTS = 100000

# Lab bench overlap/capacity (PRD section 3.8)
LAB_BUFFER_HOURS = 24
LAB_CAPACITY = 3

# Device subsidy recovery (PRD section 3.10)
STRAIGHT_LINE_MONTHS = 24
MONETIZATION_RECOVERY_BPS = 3500

# Dispute appeal window (PRD section 3.9)
APPEAL_WINDOW_DAYS = 7

# Logical clock default (PRD section 2.4)
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "AD_SHARE_BPS": 7000,
    "ROYALTY_PER_DEVICE_CENTS": 300,
    "CAMPAIGN_BUDGET_CENTS": 100000,
    "FLIGHT_START": "2026-09-01T00:00:00Z",
    "FLIGHT_END": "2026-09-30T00:00:00Z",
}
