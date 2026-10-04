"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3)."""

THRESHOLDS = {
    # Royalty accrual tiers (PRD §3.7)
    "TIER1_CAP_CENTS": 50000000,   # five hundred thousand dollars
    "TIER2_CAP_CENTS": 200000000,  # two million dollars
    "TIER1_RATE_BPS": 1000,
    "TIER2_RATE_BPS": 1200,
    "TIER3_RATE_BPS": 1500,
    # Prize pool share total (PRD §3.5)
    "TOTAL_SHARE_BPS": 10000,
    # Overall rating inclusive range (PRD §3.3)
    "RATING_MIN": 40,
    "RATING_MAX": 99,
}

TEST_DEFAULTS = {
    # Logical clock startup reading (PRD §2.4)
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "TERM_START_ON": "2026-01-01",
    "TERM_END_ON": "2026-12-31",
    "PERIOD_START_ON": "2026-08-01",
    "PERIOD_END_ON": "2026-08-31",
    # Frequently reused operator identities (opaque; only SoD compares them)
    "OPERATOR_ID": "op-1",
    "REVIEWER_ID": "reviewer-1",
}
