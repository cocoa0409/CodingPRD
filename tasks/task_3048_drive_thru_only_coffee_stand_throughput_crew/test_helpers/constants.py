"""Domain thresholds — numeric constants from the PRD's calculation rules.

The server-side logical clock starts at exactly 2026-09-01T00:00:00Z before
any request has been processed (PRD §2.4).
"""

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Loyalty tier thresholds (PRD §3.4)
GOLD_MIN_POINTS = 500
SILVER_MIN_POINTS = 200
GOLD_DISCOUNT_PCT = 0.10
SILVER_DISCOUNT_PCT = 0.05

# Build-time calculation (PRD §3.6)
BLENDED_ADD_SECONDS = 15
BUILD_CAP_SECONDS = 240
DEFAULT_CREW_ON_BAR = 2

# Staffing deficit score constants (PRD §3.5)
PEAK_MIN_CREW = 4
BASE_MIN_CREW = 2
MISSING_CREW_PENALTY = 10
MISSING_LEAD_PENALTY = 25
NO_SHOW_PENALTY = 5

# Rapid rotation ceiling (PRD §3.5)
ROTATION_MAX_MINUTES = 120

# Site approval gates (PRD §3.1)
MIN_TOTAL_STACK_CARS = 10
MIN_INGRESS_GAP_SECONDS = 30

# Throughput window spacing (PRD §3.1)
WINDOW_GAP_MIN_MINUTES = 15

# Operator eligibility (PRD §3.2)
OPERATOR_MIN_TENURE_DAYS = 365

# Refund governance (PRD §3.7)
AUTO_REFUND_MAX_CENTS = 2000

# Royalty statement constants (PRD §3.7)
BRAND_FUND_PCT = 0.02
ROYALTY_TIER1_MIN_CENTS = 1_000_000
ROYALTY_TIER2_MIN_CENTS = 5_000_000

# Payments
CARD_TOKEN_OK = "VISA-OK"
CARD_TOKEN_DECLINE = "DECLINE"

# Opaque identities used by tests (PlatformAdmin / RegionalManager)
ADMIN_USER_ID = "pa-1"
MANAGER_USER_ID = "rm-1"
