"""Domain thresholds and test defaults — numeric constants from the PRD."""

THRESHOLDS = {
    # Assessment composite weights and rating bands
    "W_GOVERNANCE": 0.40,
    "W_FINANCE": 0.35,
    "W_PROGRAM": 0.25,
    "STRONG_FLOOR": 85,
    "ADEQUATE_FLOOR": 70,
    "MARGINAL_FLOOR": 50,
    # Competitive tiers
    "TIER1_FLOOR": 90,
    "TIER2_FLOOR": 75,
    "TIER3_FLOOR": 60,
    "COMPETITIVE_SCORE_FLOOR": 60,
    "TIER2_RATE": 0.80,
    "TIER3_RATE": 0.50,
    # Match
    "MATCH_STANDARD_RATE": 0.25,
    "MATCH_REDUCED_RATE": 0.10,
    "MATCH_REDUCED_MONTHS": 24,
    # Posture
    "POSTURE_RESTRICTED_FINDINGS": 3,
    "LAPSE_POSTURE_THRESHOLD": 2,
    # CE
    "CE_WINDOW_MONTHS": 24,
    "CE_REQUIRED_CREDITS": 30,
    "LAPSE_GRACE_DAYS": 90,
    # Client files
    "MIN_HOURS_NO_OUTCOME": 2.0,
    # Reviews
    "PERFORMANCE_PASS_SCORE": 70,
    "CORRECTIVE_PLAN_DAYS": 60,
    # Enrollment
    "PASS_THRESHOLD": 70,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "DEFAULT_DELIVERY_START": "2026-09-02T00:00:00Z",
    "DEFAULT_DELIVERY_END": "2026-09-20T00:00:00Z",
    "DEFAULT_IN_SESSION_INSTANT": "2026-09-10T00:00:00Z",
    "DEFAULT_GRADE_SCORE": 90,
}
