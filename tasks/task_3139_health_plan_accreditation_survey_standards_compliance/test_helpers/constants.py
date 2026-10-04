"""Domain thresholds — numeric constants from PRD calculations (§3.7, §3.8, §3.10)."""

THRESHOLDS = {
    # Element score component weights and gap deduction (PRD §3.7)
    "FILE_WEIGHT": 0.6,
    "EVIDENCE_WEIGHT": 0.4,
    "GAP_DEDUCTION_RATE": 0.1,
    # Composite category weights (PRD §3.8)
    "WEIGHT_UM": 0.30,
    "WEIGHT_CR": 0.30,
    "WEIGHT_MRR": 0.20,
    "WEIGHT_QI": 0.20,
    # Bonus component ceilings (PRD §3.8)
    "QUALITY_BONUS_MAX": 2.0,
    "CONSUMER_BONUS_MAX": 2.0,
    # Outcome status thresholds (PRD §3.8)
    "DENIED_FLOOR": 60.00,
    "FULL_THRESHOLD": 90.00,
    "CAP_THRESHOLD": 75.00,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD §2.7)
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    # Canonical edition configuration used by the tests
    "EDITION_YEAR": 2026,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2027-12-31T23:59:59Z",
    "MIN_FILE_SAMPLE_PER_CATEGORY": 5,
    "TIMELINESS_THRESHOLD": 0.90,
    # Canonical review window
    "REVIEW_PERIOD_START": "2025-01-01T00:00:00Z",
    "REVIEW_PERIOD_END": "2025-12-31T23:59:59Z",
    # Canonical plan
    "PLAN_NAME": "Meridian Health Alliance",
    "PLAN_CODE": "MHA-01",
    # Canonical survey window
    "SURVEY_START": "2026-10-05",
    "SURVEY_END": "2026-10-09",
}
