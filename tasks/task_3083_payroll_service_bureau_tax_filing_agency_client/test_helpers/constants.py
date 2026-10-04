"""Domain constants from the PRD's calculation and clock rules (§2.5–§2.6, §3)."""

# Logical clock default before any set call (PRD §2.6).
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# STANDARD settlement window: initiated_at + 2 business days (PRD §3.4).
STANDARD_SETTLEMENT_BUSINESS_DAYS = 2

# Risk posture weighting (PRD §3.5).
NSF_RETURN_WEIGHT = 2
WIRE_NOT_CONFIRMED_WEIGHT = 1
HIGH_POSTURE_BASE = 4
ELEVATED_POSTURE_MIN_BASE = 2
SUSPENSION_STRIKE_COUNT = 3

# Late-deposit penalty tier day boundaries, inclusive (PRD §3.6).
PENALTY_TIER1_MAX_LATE_DAYS = 5
PENALTY_TIER2_MAX_LATE_DAYS = 15

# Default jurisdiction configuration used across fixtures.
DEFAULT_PENALTY_TIER1_RATE = 0.02
DEFAULT_PENALTY_TIER2_RATE = 0.05
DEFAULT_PENALTY_TIER3_RATE = 0.10
DEFAULT_UNDERPAYMENT_THRESHOLD_CENTS = 250000
