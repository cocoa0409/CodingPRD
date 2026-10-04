"""Domain thresholds — numeric constants from the PRD (§3.5, §3.6, §3.7, §3.8)."""

THRESHOLDS = {
    # Skills evaluation scoring (PRD §3.6)
    "INITIAL_PASS_THRESHOLD": 84.00,
    "RETEST_PASS_THRESHOLD": 90.00,
    # Certification (PRD §3.2)
    "MIN_EVALUATIONS": 2,
    "MIN_AVERAGE": 4.00,
    # Renewal (PRD §3.3)
    "EARLY_RENEWAL_DAYS": 90,
    "RENEWAL_MIN_SESSIONS": 2,
    "RENEWAL_WINDOW_MONTHS": 24,
    # Card validity (PRD §3.7)
    "VALIDITY_MONTHS": 24,
    # Equipment sufficiency (PRD §3.5)
    "MANIKIN_RATIO_CLASSROOM": 3,
    "MANIKIN_RATIO_BLENDED": 6,
    "AED_RATIO_DEFAULT": 6,
    "AED_RATIO_ADVANCED": 4,
    "STUDENTS_PER_INSTRUCTOR": 6,
    # Audit compliance (PRD §3.8)
    "SEVERITY_POINTS": {
        "OBSERVATION": 1.25,
        "MINOR": 4.5,
        "MAJOR": 12.5,
        "CRITICAL": 40,
    },
    "REPEAT_MULTIPLIER": 1.5,
    # Site turnover buffer (PRD §3.4)
    "SITE_TURNOVER_MINUTES": 60,
}

TEST_DEFAULTS = {
    # Startup logical clock (PRD §2.4)
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "SITE_CAPACITY": 24,
    "SESSION_CAPACITY": 6,
    "SESSION_START": "2026-10-10T14:00:00Z",
    "SESSION_END": "2026-10-10T18:00:00Z",
}
