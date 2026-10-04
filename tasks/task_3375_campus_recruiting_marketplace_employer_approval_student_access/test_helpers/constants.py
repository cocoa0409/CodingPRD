"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# The logical clock's startup default (PRD §2.5).
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Fraud risk scoring (PRD §3.2)
    "FRAUD_BASE_SCORE": 50,
    "EMAIL_DOMAIN_MATCH_POINTS": 25,
    "ESTABLISHED_TLD_POINTS": 15,
    "HYPHEN_POINTS": 10,
    "SHORT_NAME_POINTS": 10,
    "FLAG_PENALTY": 10,
    "ADJUSTMENT_MAX_ABS": 40,
    # Trust tier boundaries, inclusive upper bounds (PRD §3.2)
    "TIER_LOW_RISK_MAX": 20,
    "TIER_STANDARD_MAX": 50,
    "TIER_ELEVATED_MAX": 79,
    # Daily messaging allowance (PRD §3.8)
    "MSG_BASE_DAILY_CAP": 5,
    "UNIVERSITY_DEFAULT_MESSAGE_CAP": 10,
    # Interview schedule buffer in minutes (PRD §3.7)
    "INTERVIEW_BUFFER_MINUTES": 15,
    # Outcome report rounding (PRD §3.9)
    "RATE_DECIMAL_PLACES": 4,
}

# Tier multiplier percentages for the messaging allowance (PRD §3.8).
TIER_MULTIPLIER_PERCENT = {
    "LOW_RISK": 200,
    "STANDARD": 100,
    "ELEVATED": 40,
    "HIGH_RISK": 0,
}

TEST_DEFAULTS = {
    "UNIVERSITY_NAME": "State University",
    "UNIVERSITY_DOMAIN": "stateu.edu",
    "EVENT_STARTS_AT": "2026-10-10T09:00:00Z",
    "EVENT_ENDS_AT": "2026-10-10T17:00:00Z",
    "SESSION_SIGNUP_DEADLINE": "2026-10-09T23:59:59Z",
    "POSTING_DEADLINE": "2026-12-01T00:00:00Z",
}
