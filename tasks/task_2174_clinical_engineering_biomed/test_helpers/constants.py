"""Domain thresholds and canonical fixture values drawn from the PRD narratives."""

# Logical clock (PRD §2.5): the server starts here and must not fall back to wall clock.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Risk classification (PRD §3.2)
RISK_WEIGHTS = {"FUNCTION": 2, "PHYSICAL": 3, "MAINTENANCE": 1}
NETWORK_ADDER = 4
AGE_ADDER_5Y = 1
AGE_ADDER_8Y = 3
RISK_BAND_MIN = {"CRITICAL": 34, "HIGH": 26, "MEDIUM": 16}
PM_INTERVAL_DAYS = {"CRITICAL": 90, "HIGH": 180, "MEDIUM": 270, "LOW": 365}

# Work-order priority (PRD §3.4)
SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72}

# Service cost (PRD §3.4)
IN_HOUSE_LABOR_RATE_CENTS_PER_HOUR = 9000
AFTER_HOURS_MULTIPLIER = 1.5
DAY_SHIFT_START_HOUR = 7
DAY_SHIFT_END_HOUR = 19

# Departmental debit (PRD §2.9 / §3.5)
TIER_T0_PCT = 50
TIER_T1_PCT = 80
WARNING_PCT = 80
OVERHEAD_PCT = {"T0": 0.00, "T1": 0.05, "T2": 0.12}

# Rental billing (PRD §3.6)
RENTAL_BASE_DAILY_CENTS = 24333
RENTAL_RISK_SURCHARGE_PCT = {"CRITICAL": 0.25, "HIGH": 0.15, "MEDIUM": 0.05, "LOW": 0.00}
RENTAL_LONG_TERM_DISCOUNT_PCT = 0.10
LONG_TERM_DISCOUNT_AFTER_DAY = 7

# Capital replacement scoring (PRD §3.9)
W_AGE = 0.35
W_CONDITION = 0.30
W_BURDEN = 0.20
W_RISK = 0.15
RISK_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.25}

# Security remediation SLA in whole days (PRD §3.8)
REMEDIATION_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 90, "LOW": 180}

# PM deferral cap (PRD §3.3)
MAX_DEFERRALS = 2

# Pagination (PRD §2.3)
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100}

# Canonical operator identities used across the suite.
OPERATORS = {
    "manager": "ce-mgr-01",
    "tech_alpha": "tech-alpha",
    "tech_bravo": "tech-bravo",
    "security": "sec-01",
}
