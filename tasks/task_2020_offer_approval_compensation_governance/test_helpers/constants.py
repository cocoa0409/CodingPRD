"""Domain thresholds — numeric constants from the PRD's calculations."""

THRESHOLDS = {
    # band classification
    "ABOVE_BAND_TOLERANCE_PCT": 0.10,
    "HARD_CAP_PCT": 0.25,
    # approval chain routing
    "SIGNON_REVIEW_THRESHOLD_CENTS": 1000000,
    "TIER2_TOTAL_CASH_CENTS": 30000000,
    # offer cost
    "BENEFITS_LOAD_PCT": 0.30,
    "EQUITY_VEST_YEARS": 4,
    # peer equity
    "MIN_PEER_SNAPSHOTS": 3,
    "COMPA_RISK_LOW": 0.85,
    "COMPA_RISK_HIGH": 1.15,
    "PCT_RISK_LOW": 10,
    "PCT_RISK_HIGH": 90,
    # concession authority caps
    "RECRUITER_CONCESSION_CAP": 0.05,
    "HM_CONCESSION_CAP": 0.10,
    "VP_CONCESSION_CAP": 1.00,
    # offer expiry
    "OFFER_EXPIRY_DAYS": 10,
    # sign-on single-perk hard cap
    "SIGNON_HARD_CAP_CENTS": 2500000,
    # negotiation rounds
    "MAX_NEGOTIATION_ROUNDS": 3,
}

TEST_DEFAULTS = {
    # standard L5/T1 salary band used across most setups
    "SALARY_MIN_CENTS": 15000000,
    "SALARY_MID_CENTS": 18000000,
    "SALARY_MAX_CENTS": 21000000,
    "ANNUAL_BUDGET_CENTS": 50000000,
    "BASE_CENTS": 18000000,
    # logical clock startup default per PRD §2.4
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # 10 days after the startup clock
    "DEFAULT_EXPIRES_AT": "2026-08-11T00:00:00Z",
}
