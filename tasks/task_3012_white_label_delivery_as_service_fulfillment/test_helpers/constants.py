"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Lateness bands (seconds): <= 600 on time; (600, 1800] 25%; > 1800 full.
    "LATE_GRACE_SECONDS": 600,
    "LATE_FULL_SECONDS": 1800,
    "LATE_PARTIAL_PCT": 0.25,
    # Platform cap multiplier on delay/outage refund shares.
    "PLATFORM_DELAY_CAP_MULTIPLIER": 2.0,
    # Batch courier cost: 400 base + 150 per order.
    "BATCH_BASE_COST_CENTS": 400,
    "BATCH_PER_ORDER_CENTS": 150,
    # SLA: credits accrue when gross attainment falls below 97%.
    "CREDIT_TRIGGER_ATTAINMENT": 0.97,
    # Quotes are usable for fifteen minutes from creation.
    "QUOTE_VALIDITY_MINUTES": 15,
    # Max appeals per refund claim.
    "MAX_APPEALS": 1,
    # Batch size bounds (1..3 orders).
    "BATCH_MIN_ORDERS": 1,
    "BATCH_MAX_ORDERS": 3,
}

TEST_DEFAULTS = {
    "MERCHANT_BILLING_BALANCE_CENTS": 100000,
    "DEFAULT_REFUND_SPLIT_MERCHANT_PCT": 50,
    "STORE_RADIUS_M": 20000,
    "STORE_TIMEZONE": "UTC",
    "COURIER_CAPACITY": 4,
    "SURGE_DEFAULT": 1.0,
    "STARTUP_CLOCK_UTC": "2026-09-01T00:00:00Z",
}
