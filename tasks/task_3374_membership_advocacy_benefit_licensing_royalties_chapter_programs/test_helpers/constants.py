"""Domain thresholds and pricing constants — numeric literals from the PRD.

Every value below is stated verbatim in PRD.md (pricing schedule, royalty
tiers, escalation thresholds, governance caps, room buffer, logical clock).
"""

# Logical clock (PRD: startup default reading)
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# Membership pricing (PRD: dues and discount schedule)
BASE_ANNUAL_CENTS = 1600
MULTI_YEAR_DISCOUNT = {1: 0.0, 3: 0.10, 5: 0.20}
LOYALTY_RENEWAL_DISCOUNT = 0.05
DISCOUNT_CAP = 0.25
ALLOWED_TERM_YEARS = (1, 3, 5)

# Cancellation refunds (PRD: undiscounted monthly basis, half-up of 1600/12)
BASE_MONTHLY_CENTS = 133

# Royalty marginal tiers (PRD: annual marginal tiers)
TIER1_CAP_CENTS = 100_000_000
TIER1_RATE = 0.08
TIER2_CAP_CENTS = 500_000_000
TIER2_RATE = 0.10
TIER3_RATE = 0.12

# Escalation thresholds (PRD: at-least comparisons, inclusive 365-day window)
AGREEMENT_PROBATION_THRESHOLD = 3
PROVIDER_SUSPENSION_THRESHOLD = 5
TRAILING_WINDOW_DAYS = 365

# Fund-transfer governance caps (PRD: truncated percentages)
FOUNDATION_PER_TRANSFER_CAP_PCT = 0.05
FOUNDATION_ANNUAL_OUTFLOW_CAP_PCT = 0.15
LOBBYING_ANNUAL_DUES_CAP_PCT = 0.20

# Course sessions (PRD: chapter-room turnover buffer)
ROOM_TURNOVER_BUFFER_MINUTES = 30

# Enrollment eligibility (PRD: minimum primary-member age)
MIN_MEMBER_AGE = 50

# Well-known operator identities used by segregation-of-duties scenarios.
GOV_USER_ID = "gov-1"
FIN_USER_ID = "fin-7"
