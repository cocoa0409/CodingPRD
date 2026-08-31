"""Domain thresholds and pinned numeric constants stated in the PRD."""

# Logical clock: the server reads exactly this instant at startup (PRD 2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Pricing and reserve constants (PRD 3.3 and 3.5).
THRESHOLDS = {
    "PROGRAM_MAX_MARKUP_BPS": 250,
    "MAX_DTI_PCT": 45.00,
    "PARTICIPATION_FACTOR": 0.55,
    "FLAT_FEE_BPS": 150,
    "INCENTIVE_BPS": 25,
    "INCENTIVE_CAP_CENTS": 15000,
    "PROGRAM_RESERVE_CAP_CENTS": 250000,
    "EARLY_PAYOFF_SEASONING_MONTHS": 12,
    "PROBATION_EARLY_PAYOFF_RATE_BPS": 3000,
    "BUYBACK_ADMIN_FEE_CENTS": 25000,
    "MARKUP_BENCHMARK_BPS": 150,
    "DISPARITY_THRESHOLD_BPS": 25,
    "MIN_REVIEW_POPULATION": 4,
    "FUNDING_WINDOW_DAYS": 30,
    "MAX_RESUBMISSIONS": 2,
    "AGREEMENT_NOTICE_BUFFER_DAYS": 30,
}

# Scorecard composite weights (PRD 3.8).
SCORECARD_WEIGHTS = {
    "W_DEFAULT": 6.0,
    "W_EARLY": 2.0,
    "W_DOC": 1.5,
    "W_MARKUP": 1.0,
}

# Default onboarding values (PRD 3.1).
DEALER_DEFAULTS = {
    "PROGRAM_CODE": "PS-STANDARD",
    "FUNDING_LINE_CENTS": 50_000_000,
    "CHARGEBACK_WINDOW_DAYS": 360,
}

# Opaque operator identifiers used by the non entity-backed roles.
ADMIN_USER_ID = "pa-001"
ANALYST_USER_ID = "ca-001"
FUNDER_USER_ID = "fs-001"
COMPLIANCE_USER_ID = "co-001"
