"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Default account tuning (PRD §3.2).
    "DEFAULT_LOW_BALANCE_THRESHOLD_CENTS": 1000,
    "DEFAULT_REPLENISHMENT_AMOUNT_CENTS": 2500,
    "DEFAULT_OPENING_BALANCE_CENTS": 0,
    # Violation admin fee schedule (PRD §3.7).
    "NOTICE_1_FEE_CENTS": 500,
    "NOTICE_2_FEE_CENTS": 2500,
    "NOTICE_3_FEE_CENTS": 5000,
    "NOTICE_INTERVAL_DAYS": 30,
    "ESCALATION_DAYS_FROM_FIRST": 60,
    "REG_HOLD_THRESHOLD_CENTS": 10000,
    "MAX_NOTICES": 3,
    # Dispute windows (PRD §3.8).
    "DISPUTE_WINDOW_DAYS": 90,
    "DISPUTE_AUTO_REJECT_DAYS": 30,
    # Replenishment suspension (PRD §3.5).
    "MAX_REPLENISHMENT_FAILURES": 3,
    # Plate data agreement default fee (PRD §3.9).
    "DEFAULT_PER_LOOKUP_FEE_CENTS": 25,
}

TEST_DEFAULTS = {
    "HOME_AGENCY": {
        "agency_code": "HOME",
        "name": "Home Toll Authority",
        "home_state": "NY",
        "reciprocity_fee_bps": 100,
    },
    "AWAY_AGENCY": {
        "agency_code": "AWAY",
        "name": "Away Toll Authority",
        "home_state": "NJ",
        "reciprocity_fee_bps": 150,
    },
    "WINDOW_FROM": "2026-09-01T00:00:00Z",
    "WINDOW_TO": "2026-09-30T00:00:00Z",
    "LONG_WINDOW_TO": "2027-01-01T00:00:00Z",
    "AGREEMENT_WINDOW_TO": "2027-09-01T00:00:00Z",
}
