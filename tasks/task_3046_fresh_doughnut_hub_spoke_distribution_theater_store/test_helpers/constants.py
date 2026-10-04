"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # stale-credit tiering
    "DOZEN_CREDIT_BASE_CENTS": 1200,
    "STALE_TIER1_DOZENS": 6,
    "STALE_TIER2_DOZENS": 24,
    "TIER0_RATE": 0.50,
    "TIER1_RATE": 0.65,
    "TIER2_RATE": 0.80,
    "LATE_PENALTY_FACTOR": 0.9,
    "DISPUTE_WINDOW_HOURS": 48,
    # mix allocation / freshness
    "MIN_YIELD_RATE": 0.85,
    "FRESHNESS_HOURS": 12,
    # fundraiser pricing
    "TIER_A_MAX": 25,
    "TIER_B_MAX": 100,
    "TIER_A_PRICE_CENTS": 700,
    "TIER_B_PRICE_CENTS": 650,
    "TIER_C_PRICE_CENTS": 600,
    "CHARITY_DISCOUNT_PCT": 0.10,
    # hot-light demand response
    "DEMAND_LOW_THRESHOLD": 30,
    "DEMAND_HIGH_THRESHOLD": 120,
    "EXTEND_CAP_HIGH_MINUTES": 90,
    "EXTEND_CAP_LOW_MINUTES": 45,
    "MAX_EXTEND_MINUTES": 90,
    # mix license quota
    "LICENSE_QUOTA_FRACTION": 0.25,
}

# Logical clock default at server startup (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "HUB_CAPACITY_DOZENS": 500,
    "LINE_RATED_DOZENS_PER_HOUR": 100,
    "LINE_SERVICE_INTERVAL_HOURS": 200,
    "VEHICLE_CAPACITY_DOZENS": 200,
    "REGION": "R1",
    "PRODUCTION_DATE": "2026-09-01",
    "VARIETY_ACTIVE_FROM": "2026-01-01T00:00:00Z",
    "VARIETY_ACTIVE_UNTIL": "2027-01-01T00:00:00Z",
}
