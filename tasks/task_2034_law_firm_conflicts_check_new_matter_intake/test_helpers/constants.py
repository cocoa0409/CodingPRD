"""Domain thresholds and defaults — numeric constants named in the PRD."""

# Default logical clock reading before any clock-set call (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Credit band inclusive lower bounds (PRD sections 2.7, 3.8)
    "PRIME_MIN": 740,
    "STANDARD_MIN": 670,
    # Retainer clamps in cents (PRD section 3.8)
    "RETAINER_MIN_CENTS": 50000,
    "RETAINER_MAX_CENTS": 10000000,
    # Assessment validity window (PRD section 3.8)
    "ASSESSMENT_VALID_DAYS": 90,
    # Countersign window (PRD section 3.7)
    "COUNTERSIGN_WINDOW_DAYS": 30,
    # Waiver expiry window (PRD section 3.6)
    "WAIVER_EXPIRY_DAYS": 30,
    # Match scoring (PRD section 3.4)
    "TOKEN_OVERLAP_MIN": 80,
    "PHONETIC_SCORE": 70,
    "AFFILIATE_DEPTH_DISCOUNT": 10,
    "AFFILIATE_MAX_DEPTH": 3,
    "DEFAULT_MATCH_THRESHOLD": 60,
    "LATERAL_SWEEP_THRESHOLD": 60,
}

# Months multipliers per credit band (PRD section 3.8)
MONTHS_MULTIPLIER = {"PRIME": 1, "STANDARD": 2, "SUBPRIME": 3}

TEST_DEFAULTS = {
    "PRACTICE_GROUP": "LITIGATION",
    "PARTY_TYPE": "CORPORATION",
    # Canonical fee line set used to produce a 2,000,000-cent fee estimate:
    # 100.0 hours x 20000 cents = 2,000,000.
    "STANDARD_HOURS": 100.0,
    "STANDARD_RATE_CENTS": 20000,
    "STANDARD_FEE_ESTIMATE_CENTS": 2000000,
    "PRIME_SCORE": 800,
    "STANDARD_SCORE": 700,
    "SUBPRIME_SCORE": 600,
}
