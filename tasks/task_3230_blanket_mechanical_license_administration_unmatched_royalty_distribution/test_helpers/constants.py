"""Domain thresholds and test defaults — numeric constants from the PRD."""

# Statutory pricing constants for the schedule governing calendar 2026.
RATE_UNDER_5MIN_CENTS_2026 = 131
RATE_PER_MIN_OVER_5MIN_CENTS_2026 = 252
FIVE_MIN_SECONDS = 300

# Legacy (superseded-window) schedule used by back-dated pricing tests.
RATE_UNDER_5MIN_CENTS_LEGACY = 120
RATE_PER_MIN_OVER_5MIN_CENTS_LEGACY = 240

# Acceptance data-quality circuit breaker: unmatched must not exceed 60%.
MATCH_RATE_FLOOR_PERCENT = 60

# Claiming period: 36 months after the first day of the month following the
# report's reporting month.
HOLD_MONTHS = 36

# Dispute escalation requires at least 90 logical days OPEN.
DISPUTE_ESCALATION_DAYS = 90

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# ABA routing numbers used across fixtures.
ROUTING_VALID = "021000021"    # satisfies the ABA checksum
ROUTING_INVALID = "021000022"  # fails the ABA checksum (one digit flipped)

TEST_DEFAULTS = {
    "DSP_LEGAL_NAME": "Duetify",
    "MEMBER_A_NAME": "Alder Publishing",
    "MEMBER_B_NAME": "Birch Songs",
    "MEMBER_C_NAME": "Cedar Music",
    "IPI_A": "00000000101",
    "IPI_B": "00000000202",
    "IPI_C": "00000000303",
    "ACCOUNT_NUMBER": "123456789",
    "TAX_ID": "123456789",
}
