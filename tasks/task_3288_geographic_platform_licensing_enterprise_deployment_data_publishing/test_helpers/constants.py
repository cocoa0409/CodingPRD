"""Domain thresholds — numeric constants from the PRD's pricing and posture rules."""

THRESHOLDS = {
    # CreditPool posture defaults
    "DEFAULT_LOW_CREDIT_THRESHOLD": 500,
    # Storage billing unit size: 100 MiB
    "STORAGE_UNIT_BYTES": 104857600,
    # Concurrent-use overage tiers (cents per seat)
    "OVERAGE_TIER1_MAX_SEAT": 5,
    "OVERAGE_TIER1_CENTS": 250,
    "OVERAGE_TIER2_MAX_SEAT": 20,
    "OVERAGE_TIER2_CENTS": 400,
    "OVERAGE_TIER3_CENTS": 700,
    # Eligibility approval window in periods
    "EV_VALIDITY_PERIODS": 12,
    # Settle late fee: +10% per full pending period
    "LATE_FEE_PER_PERIOD_NUMERATOR": 11,
    "LATE_FEE_PER_PERIOD_DENOMINATOR": 10,
    # Forward projection per-seat burn per period
    "FORWARD_BURN_NAMED_USER_PER_SEAT": 2,
    "FORWARD_BURN_CONCURRENT_USE_PER_SEAT": 5,
    "FORWARD_BURN_DEPLOYMENT_SERVER_PER_SEAT": 0,
}

# Pricing tables: list of (upper_bound_inclusive_or_None, rate_per_unit)
PRICING_TIERS = {
    "GEOCODE": [(100, 4), (1000, 3), (None, 2)],
    "ANALYSIS": [(10, 40), (100, 30), (None, 20)],
    "STORAGE": [(None, 1)],
    "TILE_QUERY": [(10000, 1), (None, 1)],
    "ROUTING": [(50, 8), (None, 5)],
}

TEST_DEFAULTS = {
    "ORG_NAME": "Meridian GIS Co",
    "ORG_REGION": "US",
    "POOL_CAPACITY": 100000,
    "PRODUCT_CODE_NAMED": "DESKTOP-PRO-11",
    "PRODUCT_MAJOR_VERSION": 11,
    "GRANT_VALID_FROM": 0,
    "GRANT_VALID_TO": 365,
    "GRANT_SEATS": 10,
    "USERNAME": "ada",
    "EMAIL": "ada@meridian.example",
    "USER_LEVEL": "PROFESSIONAL",
    "CLOCK_T0": "2026-09-01T00:00:00Z",
}

ALL_SERVICE_KINDS = ["GEOCODE", "ANALYSIS", "STORAGE", "TILE_QUERY", "ROUTING"]
