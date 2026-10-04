"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Interest accrual (PRD §3.4)
ACT_365_DIVISOR = 365
ACT_360_DIVISOR = 360
THIRTY_360_DIVISOR = 360
THIRTY_360_DAYS_PER_MONTH = 30

# Service credit computation (PRD §3.12)
MONTHLY_COVERED_HOURS = 4
RATE_CENTS_PER_HOUR = 25_000
MONTHLY_CAP_CENTS = 200_000

# Defect triage priority (PRD §3.11)
SEVERITY_WEIGHTS = {"SEV1": 100, "SEV2": 50, "SEV3": 20}
AGE_STEP_HOURS = 24
AGE_STEP_WEIGHT = 10
AGE_STEP_CAP = 3
PRIORITY_THRESHOLDS = [(110, 1), (90, 2), (60, 3), (30, 4)]  # score >= t -> priority

# Customer comm wave schedule (PRD §3.10)
SECONDS_PER_DAY = 86_400
SEND_WINDOW_DAYS = 3

# Task completion grace (PRD §3.7)
COMPLETION_GRACE_MINUTES = 30

# Default logical clock (PRD §2.4)
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
