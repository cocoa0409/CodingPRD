"""Domain thresholds and shared scenario constants.

All monetary values are integer cents; statutory rates are microcents
(millionths of a cent), per PRD §2.5.
"""

# PRD §3.5 / §3.8 constants
ADMIN_FEE_PCT = 0.05
UNDERREPORT_PENALTY_PCT = 0.15
AUDIT_COST_RECOVERY_CENTS = 50000
MICROCENTS_PER_CENT = 1_000_000

# PRD §3.6 statutory split shares
RIGHTS_OWNER_SHARE = 0.50
FEATURED_ARTIST_SHARE = 0.45
NONFEATURED_SHARE = 0.05

# PRD §3.9: pool auto-becomes distribution-eligible at this campaign count
CAMPAIGNS_BEFORE_DISTRIBUTION = 3
UNCLAIMED_EXPIRY_DAYS = 365

# Shared statutory schedule "NS-1" (nonsubscription ad-supported) used across
# scenario setups: 2600 microcents per performance, 100000-cent annual minimum.
NS1_RATE_MICROCENTS = 2600
NS1_MIN_FEE_CENTS = 100000
NS1_CATEGORY = "NONSUBSCRIPTION_AD_SUPPORTED"
NS1_WINDOW_START = "2026-01-01T00:00:00Z"
NS1_WINDOW_END = "2026-12-31T00:00:00Z"

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# A batch scheduled_for timestamp that is strictly in the past relative to the
# startup clock, so execution is due immediately after planning.
PAST_SCHEDULED_FOR = "2026-08-01T00:00:00Z"

# Standard accrual-pool window covering all of calendar 2026
POOL_WINDOW_START = "2026-01-01T00:00:00Z"
POOL_WINDOW_END = "2026-12-31T00:00:00Z"
