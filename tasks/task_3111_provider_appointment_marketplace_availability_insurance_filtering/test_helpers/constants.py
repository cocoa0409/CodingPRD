"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Fee split (PRD §3.6)
    "FEE_PCT": 0.15,
    "PROCESSING_PCT": 0.029,
    "PROCESSING_FLAT_CENTS": 30,
    # Invoice tier (PRD §3.7)
    "TIER2_COUNT": 21,
    "TIER2_PCT": 0.20,
    "TIER1_COUNT": 11,
    "TIER1_PCT": 0.10,
    # Reliability (PRD §3.8)
    "NO_SHOW_MAGNITUDE": 25,
    "LATE_CANCEL_MAGNITUDE": 15,
    "RECOVERY_PER_COMPLETION": 10,
    "GATE_THRESHOLD": 50,
    "INITIAL_EPOCH": 1,
    # Attribution (PRD §3.4)
    "ATTRIBUTION_WINDOW_DAYS": 90,
    # Cancellation policy (PRD §3.5)
    "FREE_CANCEL_HOURS": 24,
    "LATE_CANCEL_FLOOR_HOURS": 2,
    # Audit severity (PRD §3.11)
    "AUDIT_SAMPLE_CAP": 20,
    "AUDIT_WARN_THRESHOLD": 0.05,
    "AUDIT_CRITICAL_THRESHOLD": 0.20,
    # Subscription default fee (PRD §3.1)
    "DEFAULT_SUBSCRIPTION_FEE_CENTS": 30000,
    # Lead time defaults (PRD §3.1)
    "DEFAULT_NEW_PATIENT_LEAD_HOURS": 24,
    "DEFAULT_EXISTING_PATIENT_LEAD_HOURS": 4,
}

TEST_DEFAULTS = {
    "COPAY_CENTS": 10000,
    "WORKED_EXAMPLE_GROSS": 9999,
    "WORKED_EXAMPLE_FEE": 1500,
    "WORKED_EXAMPLE_PROCESSING": 320,
    "WORKED_EXAMPLE_NET": 8179,
}

# Logical clock default (PRD §2.6): before any clock call the server reads
# exactly this instant.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
DEFAULT_BILLING_PERIOD = "2026-09"
