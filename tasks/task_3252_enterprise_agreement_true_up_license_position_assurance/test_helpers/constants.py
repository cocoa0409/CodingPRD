"""Domain thresholds and defaults from the PRD calculations."""

THRESHOLDS = {
    # Price-level tiering (PRD §2.7): lower-inclusive boundaries.
    "TIER_B_MIN": 250,
    "TIER_C_MIN": 2400,
    "TIER_D_MIN": 6000,
    "PRICE_MULTIPLIER_A": 1.00,
    "PRICE_MULTIPLIER_B": 0.95,
    "PRICE_MULTIPLIER_C": 0.90,
    "PRICE_MULTIPLIER_D": 0.85,
    # Server core normalization (PRD §3.4).
    "MIN_CORES_PER_HOST": 16,
    "MIN_CORES_PER_VM": 8,
    # True-up proration (PRD §3.5).
    "MONTHS_PER_YEAR": 12,
    # Benefit accrual tiers (PRD §3.7), in cents.
    "VOUCHER_TIER1_MIN_CENTS": 50_000_000,
    "VOUCHER_TIER2_MIN_CENTS": 200_000_000,
    "UPGRADE_RIGHT_MIN_CENTS": 500_000_000,
    "BENEFIT_TTL_DAYS": 365,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-09-01T00:00:00Z",
    "DEFAULT_START_DATE": "2026-09-01",
    "DEFAULT_END_DATE": "2029-08-31",
    "DEVICE_COUNT_LEVEL_A": 100,
    "UNIT_PRICE": 100_000,
    "DEPLOYMENT_DATE": "2026-09-01",
}
