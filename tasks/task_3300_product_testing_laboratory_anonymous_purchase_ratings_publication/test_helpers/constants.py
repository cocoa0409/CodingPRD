"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # selection_score
    "REFRESH_URGENCY_MONTHS_CAP": 60,
    # designation_thresholds
    "BEST_BUY_MIN": 75,
    "RECOMMENDED_MIN": 80,
    "STANDARD_MIN": 50,
    "BEST_BUY_PRICE_CAP_CENTS": 20000,
    # safety_escalation
    "RECALL_MODEL_COUNT_MIN": 2,
    # grace_window
    "GRACE_DAYS": 14,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "BUDGET_CENTS": 500000,
    "FISCAL_YEAR": 2026,
    "REPEAT_MIN": 1,
}
