"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Renewal fee tiers (PRD §3.4)
RENEWAL_TIER_MID = 5000
RENEWAL_TIER_HIGH = 20000
FEE_LOW = 1999
FEE_MID = 2999
FEE_HIGH = 3999
FEE_PLUS = 6999

# Membership lifecycle (PRD §3.4)
MEMBERSHIP_TERM_DAYS = 365
RENEWAL_GRACE_DAYS = 30
MEMBER_RETURN_WINDOW_DAYS = 90
NON_MEMBER_RETURN_WINDOW_DAYS = 30

# Allocation ETA (PRD §3.3)
TRANSFER_DAYS = 7

# Small-format store assortment cap (PRD §3.3)
SMALL_FORMAT_ASSORTMENT_CAP = 8

# Warranty claim appeal finality threshold (PRD §3.9)
CLAIM_FINAL_THRESHOLD_CENTS = 100000
MAX_APPEALS = 1

# Logical clock initial value (PRD §2.5)
CLOCK_INITIAL = "2026-09-01T00:00:00Z"

# A wide-open coupon window covering the default clock.
WINDOW_START_DEFAULT = "2026-08-01T00:00:00Z"
WINDOW_END_DEFAULT = "2026-12-31T00:00:00Z"
