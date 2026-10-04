"""Domain thresholds — numeric constants from the PRD's calculation rules."""

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # intake routing: cost questions at or above this route to NURSE
    "COST_ESCALATION_THRESHOLD_CENTS": 500000,
    # quality score: full-confidence claims volume
    "QUALITY_VOLUME_THRESHOLD": 30,
    # quality score shrinkage target
    "NETWORK_MEAN_QUALITY": 70.0,
    # provider daily booking capacity (the 8th succeeds, the 9th fails)
    "PROVIDER_DAILY_CAPACITY": 8,
    # expert opinion submit-for-review minimum received records
    "EMO_MIN_RECORDS": 3,
    # billing case settlement proposal cap
    "MAX_SETTLEMENT_PROPOSALS": 3,
    # record request retry cap
    "MAX_RETRIES": 2,
    # appeal window length in days
    "APPEAL_WINDOW_DAYS": 30,
}

WEIGHTS = {
    "W_OUTCOME": 0.5,
    "W_COST": 0.3,
    "W_ACCESS": 0.2,
}

RATES = {
    "COINSURANCE_RATE": 0.2,
    "OON_COINSURANCE_RATE": 0.4,
    "OON_NETWORK_FACTOR": 0.8,
}

TEST_DEFAULTS = {
    "DEDUCTIBLE_LIMIT_CENTS": 100000,
    "OOP_MAX_CENTS": 500000,
    "FAR_FUTURE_EXPIRY": "2027-09-01T00:00:00Z",
}
