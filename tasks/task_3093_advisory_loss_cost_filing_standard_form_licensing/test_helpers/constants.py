"""Domain thresholds — numeric constants from the PRD's pinned calculations (§2.9, §3.2-§3.4)."""

THRESHOLDS = {
    # trend_factor / indicated_change (PRD §3.3)
    "TREND_RATE_PER_PERIOD": 0.04,
    "TREND_PERIODS": 2.5,
    "TARGET_LOSS_RATIO": 0.60,
    # submission_quality_score (PRD §3.2)
    "ERROR_PENALTY_BPS": 200,
    "WARNING_PENALTY_BPS": 50,
    "DECAY_BASE": 0.5,
    "QUALITY_SCORE_START": 10000,
    # logical clock default (PRD §2.4)
    "DEFAULT_CLOCK": "2026-09-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "LINE_OF_BUSINESS": "COMMERCIAL_PROPERTY",
    "STATE_CODE": "TX",
    "OBJECTION_WINDOW_DAYS": 30,
    "MAX_LCM_DEVIATION_PCT": 25,
    "ROYALTY_RATE_BPS": 250,
    "MULTIPLIER_PCT": 110,
    "EARNED_PREMIUM_CENTS": 1000000,
    "INCURRED_LOSS_CENTS": 550000,
    "CURRENT_LOSS_COST_CENTS": 120000,
    "WEIGHT_PCT": 100,
    "RECORD_COUNT": 10,
    "WRITTEN_PREMIUM_CENTS": 100000,
}
