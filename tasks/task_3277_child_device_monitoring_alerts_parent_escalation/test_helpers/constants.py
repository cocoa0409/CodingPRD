"""Domain thresholds — numeric constants from PRD calculations."""

# Default logical clock value before any administrative clock-setting call.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Risk scoring (PRD §3.5)
SCORE_CAP = 100
CONTEXT_STEP = 0.05
CONTEXT_DEPTH_CAP = 5

# Severity classification ladder (PRD §3.6)
SEVERE_MIN = 85
HIGH_MIN = 60
MODERATE_MIN = 30

# Excerpt truncation (PRD §3.7)
EXCERPT_CAP_DEFAULT = 140
EXCERPT_CAP_TEEN_LENIENT = 70

# Subscription pricing (PRD §3.14)
BASIC_MONTHLY_CENTS = 999
STANDARD_MONTHLY_CENTS = 1999
PREMIUM_MONTHLY_CENTS = 2999
PERIOD_DAYS = 30

# Device limits per tier (PRD §3.3)
BASIC_LIMIT = 2
STANDARD_LIMIT = 5
PREMIUM_LIMIT = 10

# Bypass strikes (PRD §3.11)
STRIKE_WINDOW_DAYS = 14
LOCKDOWN_THRESHOLD = 3

# Legal reporting SLA (PRD §3.8)
REPORT_SLA_HOURS = 24

# Grant conflict padding (PRD §3.12)
GRANT_PAD_MINUTES = 5

# Crisis resource codes by alert category (PRD §3.8)
CRISIS_RESOURCE_CODES = {
    "SELF_HARM": ["CRISIS_TEXT_LINE", "988_LIFELINE"],
    "PREDATORY_CONTACT": ["NCMEC_CYBERTIPLINE"],
    "BULLYING": ["STOPBULLYING_GOV"],
    "EXPLICIT": ["COMMON_SENSE_MEDIA"],
}

# Nonexistent but well-formed UUID used by not-found tests.
MISSING_UUID = "11111111-2222-4333-8444-555555555555"
