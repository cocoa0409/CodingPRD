"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Default logical clock reading at startup (PRD section on the logical clock).
    "DEFAULT_CLOCK_UTC": "2026-09-01T00:00:00Z",
    # Inspection submission window: closed interval [scheduled_for, scheduled_for + 7 days].
    "INSPECTION_WINDOW_DAYS": 7,
    # Inspection freshness for device posture: thirty days.
    "INSPECTION_FRESHNESS_DAYS": 30,
    # Install expiry warning window driving DEGRADED posture.
    "INSTALL_EXPIRY_WARNING_DAYS": 7,
    # Campus posture aggregation fractions.
    "CAMPUS_CRITICAL_OUT_FRACTION": 0.25,
    "CAMPUS_DEGRADED_FRACTION": 0.50,
    # Walk-path (pessimistic) obstruction multiplier.
    "OBSTRUCTION_MULTIPLIER": 1.30,
    # Replenishment: exactly one pad unit per event.
    "REPLENISHMENT_PAD_QUANTITY": 1,
}

TEST_DEFAULTS = {
    "RESPONSE_TIME_TARGET_SECONDS": 240,
    "AVG_WALK_SPEED_MPS": 1.5,
    "PAD_SHELF_LIFE_MONTHS": 24,
    "BATTERY_SHELF_LIFE_MONTHS": 48,
    "LOT_MANUFACTURER_EXPIRES_AT": "2030-01-01T00:00:00Z",
    "QUANTITY_RECEIVED": 5,
    "SESSION_CAPACITY": 5,
    "CERT_MONTHS_GRANTED": 24,
}
