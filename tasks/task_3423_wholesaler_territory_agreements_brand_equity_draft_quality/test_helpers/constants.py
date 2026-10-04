"""Domain thresholds and constants — values pinned by the PRD text."""

# Logical clock (PRD section 2.5): startup default.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Keg staleness thresholds in whole days (PRD section 3.6).
STALE_AGE_DAYS = 90
CRITICAL_AGE_DAYS = 120
SECONDS_PER_DAY = 86400

# Minimum spacing between accepted audits on one account (PRD section 3.6).
AUDIT_MIN_GAP_SECONDS = 604800  # exactly seven days

# Default draft-line cleaning frequency (PRD section 3.6).
DEFAULT_LINE_CLEANING_FREQUENCY_DAYS = 14

# Wholesaler suspension threshold: count moving 2 -> 3 suspends (PRD 3.6).
SUSPENDED_ACCOUNT_THRESHOLD = 3

# Successor qualification (PRD section 3.3).
QUALIFY_THRESHOLD = 70.00
FIN_WEIGHT = 0.5
WH_WEIGHT = 0.3
MKT_WEIGHT = 0.2

# Performance composite (PRD section 3.8).
CORRECTIVE_FLOOR = 70.00
STANDARD_WEIGHTS = {"distribution": 0.40, "freshness": 0.30, "share": 0.30}
SHARE_TILTED_WEIGHTS = {"distribution": 0.25, "freshness": 0.25, "share": 0.50}

# Equity index blend (PRD section 3.2).
EQUITY_DIST_WEIGHT = 0.5
EQUITY_FRESH_WEIGHT = 0.3
EQUITY_SHARE_WEIGHT = 0.2

# Allocation waterfall (PRD section 3.5).
TIER_MULT = {"GOLD": 1.2, "SILVER": 1.0, "BRONZE": 0.8}
DEFAULT_MIN_GUARANTEE_CASES = 100
DEFAULT_TERRITORY_CAP_PCT = 0.40

# POS annual value caps in integer cents (PRD section 3.7).
POS_CAP_CENTS = {"TX": 30000, "CA": 25000}
POS_CAP_DEFAULT_CENTS = 20000

# Transfer windows (PRD sections 3.3 and 3.4).
ROFR_WINDOW_DAYS = 30
CONSUMMATION_WINDOW_DAYS = 60

# Portfolio concentration rule (PRD section 3.1).
COMPETING_MIN_COUNT = 4
CONCENTRATION_LIMIT = 0.50
COMPETING_SUPPLIER_TYPES = ("CRAFT", "IMPORT")

# Pagination defaults (PRD section 2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
