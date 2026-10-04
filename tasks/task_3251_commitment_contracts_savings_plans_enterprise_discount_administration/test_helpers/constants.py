"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # Marketplace weighting inside the shortfall computation
    "MARKETPLACE_BASE_WEIGHT": 0.5,
    "TOP_TIER_MARKETPLACE_WEIGHT": 1.0,
    # Early-termination penalty rate (half of remaining commitment)
    "EARLY_TERM_PENALTY_RATE": 0.5,
    # COHORT_WEIGHTED forecast weights
    "COHORT_W1": 0.5,
    "COHORT_W2": 0.3,
    "COHORT_W3": 0.2,
    # Renewal forecast minimum window
    "MIN_FORECAST_WINDOW": 3,
}

TEST_DEFAULTS = {
    "ORG_CEILING": 100000,
    "ORG_QUOTA": 100,
    "COMMITTED_SPEND": 1000000,
    "DEFAULT_TERM_START": "2026-09-01T00:00:00Z",
    "DEFAULT_TERM_END": "2027-09-01T00:00:00Z",
    "DEFAULT_CLOCK_START": "2026-09-01T00:00:00Z",
    "GRANT_EXPIRY": "2026-12-01T00:00:00Z",
    "USAGE_HOUR_00": "2026-09-01T00:00:00Z",
}
