"""Domain thresholds — numeric constants from PRD calculations."""
THRESHOLDS = {
    # lot complaint posture thresholds (PRD §3.2)
    "WATCH_THRESHOLD": 3,
    "HOLD_THRESHOLD": 7,
    # refill cadence tolerance fraction (PRD §3.5): earliest refill at 3/4 of supply
    "EARLY_REFILL_TOLERANCE_FRACTION": 0.25,
    # savings-card program cap per fill, in cents (PRD §3.10)
    "CARD_MAX_PER_FILL_CAP_CENTS": 20000,
    # savings-card annual allowance multiplier (PRD §3.10)
    "CARD_ANNUAL_FILL_MULTIPLIER": 12,
    # pro-rata warranty credit applies at this generation or later (PRD §3.8)
    "PRO_RATA_MIN_GENERATION": 3,
    # states excluded from savings-card program (PRD §3.10)
    "CARD_EXCLUDED_STATES": ["MA", "CA", "WA"],
}

TEST_DEFAULTS = {
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "DOB": "1980-01-01",
    "STATE_CODE": "TX",
    "LIST_PRICE_CENTS": 8900,
    "WEAR_DAYS": 14,
    "GENERATION": 3,
    "WRITTEN_ON": "2026-08-15",
    "MANUFACTURE_DATE": "2026-08-01",
    "EXPIRY_DATE": "2027-08-01",
}

USER_IDS = {
    "PLATFORM_ADMIN": "test-platform-admin-1",
    "COVERAGE_REVIEWER": "test-coverage-reviewer-1",
    "FULFILLMENT_AGENT": "test-fulfillment-agent-1",
    "BILLING_AGENT": "test-billing-agent-1",
    "WARRANTY_REVIEWER": "test-warranty-reviewer-1",
    "QUALITY_ENGINEER": "test-quality-engineer-1",
    "PATIENT_SUPPORT_AGENT": "test-patient-support-agent-1",
}
