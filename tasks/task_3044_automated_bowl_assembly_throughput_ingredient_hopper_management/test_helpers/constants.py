"""Domain thresholds and numeric constants from the PRD."""

THRESHOLDS = {
    # A sensor reading at or below 200 grams declares depletion (PRD §3.4).
    "HOPPER_DEPLETION_GRAMS": 200,
    # abs(drift_pct) strictly greater than 3.0 quarantines the hopper (PRD §2.7).
    "DRIFT_THRESHOLD_PCT": 3.0,
    # abs(variance_pct) at most 5.0 passes portion verification (PRD §2.7).
    "PORTION_TOLERANCE_PCT": 5.0,
    # A hopper's drift is computed over the most recent 10 verifications (PRD §2.7).
    "DRIFT_WINDOW_SIZE": 10,
    # Fewer than 3 samples means drift_pct is null (PRD §2.7).
    "DRIFT_MIN_SAMPLES": 3,
    # Routing threshold: complexity score at most 8 routes AUTOMATED (PRD §3.5).
    "ROUTING_THRESHOLD": 8,
    # Queue-time target used by throughput reporting (PRD §3.9).
    "QUEUE_TARGET_SECONDS": 300,
    # Daily refill budget per restaurant in grams (PRD §2.10).
    "DAILY_REFILL_BUDGET_GRAMS": 50000,
    # An order's fourth failed verification cancels it (PRD §3.6).
    "REMAKE_LIMIT": 3,
    # Calibration coefficient bounds, inclusive (PRD §3.1 / §3.6).
    "COEFFICIENT_MIN": 0.5,
    "COEFFICIENT_MAX": 2.0,
}

TEST_DEFAULTS = {
    # The logical clock reads this instant before any OpsAdmin sets it (PRD §2.4).
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "LINE_RATE_AUTOMATED": 45,
    "LINE_RATE_MANUAL": 120,
    "CALIBRATION_DEFAULT": 1.0,
    "EXTRA_MULTIPLIER": 1.5,
    "SANITATION_INTERVAL_HOURS": 4,
}
