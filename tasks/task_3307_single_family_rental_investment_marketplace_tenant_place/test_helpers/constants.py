"""Domain thresholds and defaults derived from the PRD's numeric rules."""

# Logical clock
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Offer / negotiation
EARNEST_MIN_CENTS = 50_000
OFFER_TTL_HOURS = 72
MAX_NEGOTIATION_ROUNDS = 5

# Payment record lateness
LATE_GRACE_DAYS = 5

# Certification
INSPECTION_MAX_AGE_DAYS = 180

# Underwriting
REDACTED_VACANCY_UPLIFT_BPS = 300
MONTHS_PER_YEAR = 12

# Guarantee
DAYS_PER_MONTH = 30

# Bulk discount tiers (inclusive thresholds)
BULK_TIER_2_BPS = 100
BULK_TIER_5_BPS = 300
BULK_TIER_10_BPS = 500
