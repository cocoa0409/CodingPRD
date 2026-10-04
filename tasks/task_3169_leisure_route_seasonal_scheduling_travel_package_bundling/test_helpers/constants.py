"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Default logical-clock instant read before any set call (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Publish horizon: first_operating_date must be at least 180 whole days
    # ahead of the logical clock; exactly 180 is allowed (PRD §3.2).
    "PUBLISH_HORIZON_MIN_DAYS": 180,
}

TEST_DEFAULTS = {
    "BASE_FARE_CENTS": 9900,
    "WEEKLY_FREQUENCY_CAP": 2,
    "SEAT_CAPACITY": 156,
    "DAILY_UTILIZATION_CAP_MINUTES": 480,
    "PEAK_DAY_CAP_MINUTES": 720,
    "BLOCK_MINUTES": 240,
}
