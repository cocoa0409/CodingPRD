"""Domain thresholds — numeric constants from PRD calculations."""

# Logical clock startup instant (PRD section 2.7)
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# Lead time estimation (PRD section 3.3)
HOURS_PER_DAY = 24

# Promised ship date buffers (PRD section 3.3)
BUFFER_DAYS_FEDERAL = 2
BUFFER_DAYS_PREMIER = 1
BUFFER_DAYS_STANDARD = 0
QTY_BULK_THRESHOLD = 50
BULK_BUFFER_DAYS = 3

# Order pricing tier discounts (PRD section 3.3)
DISCOUNT_STANDARD = 0.00
DISCOUNT_PREMIER = 0.08
DISCOUNT_FEDERAL = 0.12

# Build queue scoring weights (PRD section 3.4)
WEIGHT_PROMISE = 0.6
WEIGHT_LINE_COUNT = 0.3
WEIGHT_TIER = 0.1
TIER_WEIGHT_FEDERAL = 3
TIER_WEIGHT_PREMIER = 2
TIER_WEIGHT_STANDARD = 1

# Support SLA response hours (PRD section 3.8)
SLA_BASIC_HOURS = 72
SLA_NBD_HOURS = 24
SLA_ONSITE_4H_HOURS = 4
NBD_CUTOFF_HOUR = 17

# Recovery credit percentages (PRD section 3.9)
ESTIMATE_PCT = 0.30
GRADE_POOR_PCT = 0.10
GRADE_FAIR_PCT = 0.25
GRADE_GOOD_PCT = 0.45

THRESHOLDS = {
    "QTY_BULK_THRESHOLD": QTY_BULK_THRESHOLD,
    "NBD_CUTOFF_HOUR": NBD_CUTOFF_HOUR,
}
