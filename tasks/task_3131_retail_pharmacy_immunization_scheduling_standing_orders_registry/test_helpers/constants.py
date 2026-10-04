"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Excursion tier boundaries (PRD §3.2)
    "MINOR_MAX_C": 2.0,
    "MODERATE_MAX_C": 5.0,
    # Check-in window (PRD §3.4): slot_start - 30min through slot_start + 60min
    "CHECKIN_EARLY_MINUTES": 30,
    "CHECKIN_LATE_MINUTES": 60,
    # Observation default (PRD §3.7)
    "DEFAULT_OBSERVATION_MINUTES": 15,
    "HIGH_RISK_OBSERVATION_MINUTES": 30,
    # Daily dose cap default (PRD §3.1)
    "DEFAULT_MAX_DOSES_PER_PATIENT_PER_DAY": 2,
    # Coinsurance denominator (PRD §3.6)
    "COINSURANCE_DENOMINATOR": 100,
}

TEST_DEFAULTS = {
    "CASH_PRICE_CENTS": 5000,
    "STARTUP_CLOCK": "2026-09-01T00:00:00Z",
}
