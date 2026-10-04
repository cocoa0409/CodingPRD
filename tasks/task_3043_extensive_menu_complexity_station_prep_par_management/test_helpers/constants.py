"""Domain thresholds — numeric constants stated by the PRD."""

# Logical clock startup default (PRD section 2.4).
CLOCK_START = "2026-09-01T00:00:00Z"

# Prep-quantity calculation constants (PRD section 3.4).
OPTIMISTIC_BUFFER_PCT = 0.05
CONSERVATIVE_BUFFER_PCT = 0.15
SERVICE_WINDOW_HOURS = 12

# Slice-yield constants (PRD section 3.7).
SLICES_PER_CAKE = 14
CAKE_UNIT_COST_CENTS = 2500

# Station load-score constants (PRD section 3.8).
MODIFIER_MULT = 1.25
PEAK_WAIT_THRESHOLD_MINUTES = 45
PEAK_LOAD_MULTIPLIER = 1.5
LOAD_SCORE_CAP = 2.0

# Over-prep penalty tiers (PRD section 3.8).
TIER1_UPPER = 0.05
TIER2_UPPER = 0.12
TIER3_UPPER = 0.25
TIER0_POINTS = 0
TIER1_POINTS = 10
TIER2_POINTS = 25
TIER3_POINTS = 50

# Par-health critical fraction (PRD section 3.6).
PAR_CRITICAL_FRACTION = 0.25

TEST_DEFAULTS = {
    "RESTAURANT_NAME": "Ridgeview",
    "RESTAURANT_CODE": "RIDGE",
    "WEEKLY_BAKERY_BUDGET_CENTS": 100000,
}
