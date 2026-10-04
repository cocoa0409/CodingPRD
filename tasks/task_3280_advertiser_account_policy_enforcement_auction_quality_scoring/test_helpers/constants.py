"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Reserve rank: ads with ad_rank below this are excluded from the auction.
    "AD_RANK_RESERVE": 20000,
    # Reserve CPC: charged when there is no runner-up (min with winner bid).
    "RESERVE_CPC_CENTS": 5,
    # Daily pacing: a campaign-day may serve at most twice the daily budget (inclusive).
    "DAILY_OVERDELIVERY_FACTOR": 2,
    # Billing threshold ladder rungs.
    "THRESHOLD_LADDER": [50000, 150000, 300000, 500000],
    # Initial threshold.
    "INITIAL_THRESHOLD_CENTS": 50000,
    # Minimum daily budget.
    "MIN_DAILY_BUDGET_CENTS": 100,
    # Invoice due date offset in days.
    "INVOICE_DUE_DAYS": 14,
    # Appeal window: half-open [suspended_at, suspended_at + 30 days).
    "APPEAL_WINDOW_DAYS": 30,
    # Cooling-off buffer after an UPHELD appeal decision.
    "APPEAL_COOLDOWN_DAYS": 14,
    # Monthly cap day-factor.
    "DAYS_FACTOR_NUMERATOR": 304,
    "DAYS_FACTOR_DENOMINATOR": 10,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "DEFAULT_DATE": "2026-09-01",
    "DEFAULT_END_DATE": "2026-12-31",
    "BUDGET": 1000,
    "BID": 200,
    "QUALITY_MAX_SCORES": {"quality_ectr_score": 10, "quality_relevance_score": 10, "quality_lp_score": 10},
    "QUALITY_MID_SCORES": {"quality_ectr_score": 8, "quality_relevance_score": 7, "quality_lp_score": 6},
    "QUALITY_FLAT_SCORES": {"quality_ectr_score": 5, "quality_relevance_score": 5, "quality_lp_score": 5},
}
