"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # Acuity score band boundaries (PRD §3.3)
    "EMERGENT_SCORE_THRESHOLD": 80,
    "URGENT_SCORE_THRESHOLD": 50,
    "STANDARD_SCORE_THRESHOLD": 30,
    "RED_FLAG_WEIGHT": 20,
    "AGE_GERIATRIC_THRESHOLD": 75,
    "AGE_SENIOR_THRESHOLD": 65,
    # Dispatch selector (PRD §3.4)
    "DISPATCH_PENALTY_PER_ACTIVE": 100,
    # Overtime premium (PRD §3.4)
    "OVERTIME_CENTS_PER_MINUTE": 75,
    # Readmission risk tiers (PRD §3.8)
    "HIGH_THRESHOLD": 60,
    "MEDIUM_THRESHOLD": 30,
}

TEST_DEFAULTS = {
    "URGENT_BASE_RATE_CENTS": 40000,
    "STANDARD_BASE_RATE_CENTS": 25000,
    "POS_MODIFIER": 0.85,
    "MAX_CLAIM_CENTS": 1000000,
    "URGENT_WINDOW_MINUTES": 60,
    "STANDARD_WINDOW_MINUTES": 240,
}
