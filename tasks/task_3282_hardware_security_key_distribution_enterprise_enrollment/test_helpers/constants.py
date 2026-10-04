"""Domain thresholds — numeric constants from PRD calculations."""
THRESHOLDS = {
    # credit-unit conversion: 100 cents per credit unit (ceil)
    "CREDIT_UNIT_CENTS": 100,
    # volume tiers on purchase-order line_count (>= boundaries inclusive)
    "VOLUME_TIER_100_PCT": 10,
    "VOLUME_TIER_100_MIN": 100,
    "VOLUME_TIER_50_PCT": 5,
    "VOLUME_TIER_50_MIN": 50,
    # enrollment validity / expiring window
    "ENROLLMENT_VALIDITY_DAYS": 365,
    "EXPIRING_WINDOW_DAYS": 30,
    # refresh run cost per account
    "REFRESH_CREDIT_COST": 1,
    # temporary-access duration window (inclusive)
    "GRANT_MIN_HOURS": 1,
    "GRANT_MAX_HOURS": 72,
}

TEST_DEFAULTS = {
    "UNIT_PRICE_CENTS": 150,
    "FIRMWARE_VERSION": "5.4.3",
    "SHIPPING_LOCATION": "HQ",
    "CLOCK_START": "2026-09-01T00:00:00Z",
}
