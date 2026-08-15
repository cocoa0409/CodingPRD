"""Domain thresholds and pinned fixture values from the PRD (§2.6, §3)."""

# Logical clock (PRD §2.6): startup default before any call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DISCOVERY_WINDOW_DAYS = 120          # PRD §3.4: discovery_close_at = clock + 120 days
RESPONSE_DUE_DAYS = 10               # PRD §3.4: response_due_at = issued_at + 10 days
EXTENDED_DUE_DAYS = 5                # PRD §3.4: extended_due_at = ruling clock + 5 days
DISCOVERY_CLOSE_DEFAULT_ISO = "2026-11-29T00:00:00Z"  # 2026-08-01 + 120 days

# Fiscal constants (PRD §3.3).
RR_MATCH_TOLERANCE_CENTS = 100

# Class cost allocation weights (PRD §3.7).
DEMAND_PCT = 0.60
ENERGY_PCT = 0.25
CUSTOMER_PCT = 0.15

# Gradualism cap factor (PRD §3.7).
GRADUALISM_FACTOR = 1.5

# True-up de-minimis (PRD §3.8).
DE_MINIMIS_ABS_CENTS = 100000
DE_MINIMIS_PCT = 0.005

# Canonical case numbers used across fixtures.
CASE_NUMBER_MAIN = "UR-2026-104"
CASE_NUMBER_ALT = "UR-2026-999"

# Canonical computed figures for the shared fixture (PRD §3.3, §3.7, §3.8):
# COS = 1,650,000,000; rate base as-filed 3,300,000,000; return 247,500,000.
CANONICAL_PROPOSED_RR_CENTS = 1897500000
CANONICAL_SETTLEMENT_RR_CENTS = 1850000000
CANONICAL_COS_CENTS = 1650000000
CANONICAL_RATE_BASE_AS_FILED_CENTS = 3300000000
CANONICAL_RATE_BASE_AS_AUDITED_CENTS = 2400000000
CANONICAL_RETURN_AS_FILED_CENTS = 247500000
CANONICAL_RETURN_AS_AUDITED_CENTS = 180000000
CANONICAL_RR_AS_FILED_CENTS = 1897500000
CANONICAL_RR_AS_AUDITED_CENTS = 1830000000

# Light fixture (single 1e9 O&M entry, one 2.4e9 net rate-base item):
# RR = 1,000,000,000 + round(2,400,000,000 * 750/10000) = 1,180,000,000.
LIGHT_PROPOSED_RR_CENTS = 1180000000
