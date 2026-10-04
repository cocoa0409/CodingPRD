"""Domain thresholds and shared values — numeric constants from the PRD."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
CLOCK_DEFAULT_EFFECTIVE_AT = "2026-09-01T00:00:00Z"

# Appetite rule window covering the whole test horizon.
RULE_WINDOW_FROM = "2026-01-01T00:00:00Z"
RULE_WINDOW_TO = "2027-01-01T00:00:00Z"

# Risk-score routing thresholds (PRD §3.3).
REFER_FLOOR = 60
DECLINE_FLOOR = 85
SIGNAL_TIER_POINTS = {80: 25, 50: 15, 20: 8, 1: 3}
HAZARD_YES_POINTS = 10

# Premium formula constants (PRD §3.4).
TIER_2_FLOOR = 50
TIER_3_FLOOR = 200
TIER_2_MULT = 1.15
TIER_3_MULT = 1.30
PKG_2_DISCOUNT = 0.10
PKG_3_DISCOUNT = 0.20
CLAIMS_FREE_DISCOUNT = 0.05
EXPOSURE_AUDIT_UPLIFT = 0.03

# Proration constants (PRD §3.5 / §3.6).
TERM_DAY_COUNT = 365
SHORT_RATE_FACTOR = 0.90

# Quote validity window (PRD §3.3): 168 hours.
QUOTE_TTL_HOURS = 168

# Claim triage thresholds (PRD §3.7).
FAST_TRACK_CAP_CENTS = 100000
COMPLEX_FLOOR_EXCLUSIVE_CENTS = 500000
CLAIM_AMOUNT_FLOOR_CENTS = 100
EVIDENCE_MIN_BYTES = 1024
EVIDENCE_MAX_BYTES = 10485760

# Non-renewal statutory minimums (PRD §3.6).
STATUTE_MIN_DAYS = {
    "APPETITE_CHANGE": 45,
    "CARRIER_WITHDRAWAL": 60,
    "RISK_ESCALATION": 30,
}

# Segregation-of-duties test identities.
ADJUSTER_1 = "adj-1"
ADJUSTER_2 = "adj-2"
FINANCE_1 = "fin-1"
UNDERWRITER_1 = "uw-1"
COMPLIANCE_1 = "co-1"
