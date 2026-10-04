"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Response window: sent_at + 14 days, exclusive upper bound
    "WINDOW_DAYS": 14,
    # Posture ladder
    "WATCH_SCORE_LT": 800,
    "PROBATION_SCORE_LT": 700,
    "SUSPENDED_FLAGS_GTE": 3,
    "PROBATION_FLAGS_GTE": 2,
    # Incentive tiering
    "MIN_RESPONSE_RATE": 0.30,
    "GOLD_SCORE_GTE": 900,
    "SILVER_SCORE_GTE": 800,
    "BRONZE_SCORE_GTE": 700,
    "GOLD_RATE": 0.08,
    "SILVER_RATE": 0.05,
    "BRONZE_RATE": 0.02,
    # Score computation: deduction per confirmed flag
    "FLAG_DEDUCTION": 25.0,
    # Sampling
    "MAX_PER_DEALER_KIND": 20,
    "CONTACT_SUPPRESSION_DAYS": 90,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-10-01T00:00:00Z",
    "NEXT_PERIOD_START": "2026-10-01T00:00:00Z",
    "NEXT_PERIOD_END": "2026-11-01T00:00:00Z",
    "MARGIN_CENTS": 100000,
    "COMPARABILITY_FACTOR": 1.0,
}
