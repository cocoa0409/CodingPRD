"""Domain thresholds and defaults — numeric constants from the PRD (§3)."""

THRESHOLDS = {
    # Platform fee tiers (§3.2/§2.9): average-rate on gross.
    "PLATFORM_TIER1_THRESHOLD": 1_000_000,
    "PLATFORM_TIER2_THRESHOLD": 10_000_000,
    # Freight consolidation surcharges (§3.5).
    "FREIGHT_WEIGHT_THRESHOLD_KG": 22_000,
    "FREIGHT_VOLUME_THRESHOLD_M3": 67,
    # Reprint approval gate (§3.11): score must be < 70.
    "REPRINT_RISK_GATE": 70,
    # Distributor msrp positioning bounds (§3.8): [0.30, 0.60].
    "MSRP_POSITIONING_MIN": 0.30,
    "MSRP_POSITIONING_MAX": 0.60,
    # Retail release delay (§3.6): 90 days after last wave dispatched.
    "RETAIL_DELAY_DAYS": 90,
    # Localization royalty bounds (§3.10): strictly (0, 0.25).
    "ROYALTY_PCT_MAX_EXCLUSIVE": 0.25,
}

TEST_DEFAULTS = {
    "GOAL_CENTS": 1_000,
    "LEVEL_PRICE_CENTS": 5_000,
    "LEVEL_NAME": "L",
    "CURRENCY": "USD",
    "REGION": "NA",
    "OWNER_USER_ID": "co-1",
    "FACTORY_NAME": "F",
    "TIER_MIN_UNITS": 1,
    "TIER_UNIT_PRICE_CENTS": 5_000,
}

# Logical-clock defaults used across scenarios.
CLOCK_START = "2026-09-01T00:00:00Z"
