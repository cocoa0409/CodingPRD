"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # fraud behavioral scoring (PRD §3.4)
    "VELOCITY_THRESHOLD_SECONDS": 8,
    "DEVICE_REUSE_THRESHOLD": 2,
    "FRAUD_SOFT_THRESHOLD": 1,
    "FRAUD_HARD_THRESHOLD": 2,
    "FRAUD_STRIKES_DEBAR": 3,
    # FNOL triage (PRD §3.7)
    "FRAUD_SCORE_AUTO_THRESHOLD": 0.30,
    "INSTANT_PAY_LIMIT_CENTS": 250000,
    # appeal window (PRD §3.9)
    "APPEAL_WINDOW_DAYS": 30,
    "MAX_APPEALS_PER_CLAIM": 1,
    # quote / lapse timing (PRD §3.4, §3.6)
    "QUOTE_TTL_DAYS": 30,
    "DEFAULT_PREMIUM_GRACE_DAYS": 60,
}

TEST_DEFAULTS = {
    "COVERAGE_CENTS": 500000,
    "PREMIUM_CENTS": 100000,
    "CLEAN_VELOCITY_SECONDS": 60,
    "CLEAN_DEVICE_REUSE": 0,
    "CLEAN_IPA_ACK": True,
    "ESCALATING_FRAUD_SCORE": 0.90,
    "CLEAN_FRAUD_SCORE": 0.10,
}
