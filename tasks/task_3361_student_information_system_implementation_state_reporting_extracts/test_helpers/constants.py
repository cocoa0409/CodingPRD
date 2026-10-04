"""Domain thresholds and standard fixture constants from the PRD."""

# Logical clock default (PRD §2.4): before any call the clock reads this instant.
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Calculation thresholds (PRD §2.6, §3.3, §3.5, §3.6, §3.7)
THRESHOLDS = {
    "AT_RISK_THRESHOLD": 0.05,
    "CHRONIC_ABSENCE_THRESHOLD": 0.10,
    "FTE_CAP": 1.0,
    "SEVERITY_CAP": 100,
    "ESCALATION_WINDOW_HOURS": 48,
    "SECTION_BUFFER_MINUTES": 10,
    "AUTO_WITHDRAW_STREAK": 3,
    "MIN_MEMBERSHIP_DAYS": 10,
    "INSTRUCTIONAL_DAYS": 180,
}

# Standard fixture school year: half-open [2026-08-01, 2027-06-01), 304 days.
DATES = {
    "YEAR_START": "2026-08-01T00:00:00Z",
    "YEAR_END": "2027-06-01T00:00:00Z",
    "COUNT_DATE": "2026-10-01T00:00:00Z",
    "WINDOW_OPENS": "2027-06-15T00:00:00Z",
    "WINDOW_CLOSES": "2027-07-15T00:00:00Z",
    "TARGET_YEAR_START": "2027-08-01T00:00:00Z",
    "TARGET_YEAR_END": "2028-06-01T00:00:00Z",
    "TARGET_COUNT_DATE": "2027-10-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "DISTRICT_NAME": "Lone Star ISD",
    "STATE_CODE": "TX",
}
