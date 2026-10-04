"""Domain thresholds — numeric constants from the PRD's calculation rules (§3.3, §3.7)."""

THRESHOLDS = {
    # Share capacity (PRD §2.5)
    "MARKET_CAPACITY_BPS": 10000,
    # Demand tier boundaries, ratio of allocated_bps to 10000 (PRD §3.3)
    "TIER_2_THRESHOLD_RATIO": 0.50,
    "TIER_3_THRESHOLD_RATIO": 0.80,
    "TIER_2_ALLOCATED_BPS": 5000,
    "TIER_3_ALLOCATED_BPS": 8000,
    "TIER_PRICE_STEP_PCT": 0.25,
    # Volume discount bands in basis points (PRD §3.3)
    "VOLUME_DISCOUNT_2500_BPS": 2500,
    "VOLUME_DISCOUNT_2500_PCT": 0.05,
    "VOLUME_DISCOUNT_5000_BPS": 5000,
    "VOLUME_DISCOUNT_5000_PCT": 0.10,
    # Offer TTL (PRD §3.4)
    "OFFER_TTL_SECONDS": 300,
    # Duplicate-lead lookback (PRD §3.4)
    "DUPLICATE_WINDOW_DAYS": 30,
    # Call recording retention (PRD §3.8)
    "RECORDING_RETENTION_DAYS": 90,
    # Campaign length bounds (PRD §3.3)
    "DURATION_DAYS_MIN": 1,
    "DURATION_DAYS_MAX": 90,
    # Score weights (PRD §3.7)
    "W_ACCEPTANCE": 0.25,
    "W_CONVERSION": 0.20,
    "W_RESPONSE": 0.20,
    "W_CONNECTION": 0.20,
    "W_RATING": 0.15,
}

TEST_DEFAULTS = {
    "BASE_LEAD_PRICE_CENTS": 10000,
    "SHARE_BPS": 6000,
    "DURATION_DAYS": 30,
    # Reference clock instants used across the suite.
    "CLOCK_START": "2026-09-01T00:00:00Z",
}
