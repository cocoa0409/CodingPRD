"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Pricing tiers
    "DEFAULT_MARKUP_PCT": 0.15,
    "VOLUME_DISCOUNT_THRESHOLD": 100,
    "VOLUME_DISCOUNT_MARKUP_PCT": 0.12,
    "PREMIUM_MARKUP_PCT": 0.20,
    # Ingredient yield factors
    "DOUGH_YIELD": 0.85,
    "FOOD_INGREDIENT_YIELD": 0.92,
    "PACKAGING_YIELD": 1.00,
    # Food-cost variance severity bands
    "GREEN_THRESHOLD": 0.05,
    "YELLOW_THRESHOLD": 0.10,
    # Rebate accrual rates
    "ELIGIBLE_RATE": 0.05,
    "CONDITIONAL_RATE": 0.02,
    "PROMOTION_BOOST": 1.5,
    # Rebate pool
    "POOL_RATE": 0.10,
    "HOLDBACK_DAYS": 30,
    # Compliance tiers
    "FULL_COMPLIANCE_THRESHOLD": 0.95,
    "PROBATION_THRESHOLD": 0.80,
    # Stale order expiry (ops runs)
    "DRAFT_EXPIRY_RUNS": 2,
    "SUBMITTED_EXPIRY_RUNS": 1,
}

TEST_DEFAULTS = {
    "BASE_WEEKLY_CAPACITY": 100000,
    "CREDIT_LIMIT_CENTS": 100000000,
    "BASE_COST_CENTS": 1000,
    "WEEK_START": "2026-09-07T00:00:00Z",
    "CLOCK_START": "2026-09-01T00:00:00Z",
}
