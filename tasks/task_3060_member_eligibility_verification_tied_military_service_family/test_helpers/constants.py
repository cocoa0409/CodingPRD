"""Domain thresholds and constants from the PRD's calculation rules."""

# Logical clock default (PRD: the logical clock reads exactly
# 2026-09-01T00:00:00Z before any set call).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Lineage (PRD §3.3): sponsor lineage_depth plus one must not exceed 3.
MAX_LINEAGE_DEPTH = 3

# SCRA rate relief (PRD §3.6.1).
SCRA_CAP_BPS = 600
MAX_RELIEF_PERIODS = 60
OPEN_ENDED_PERIODS = 12

# Survivor continuance (PRD §3.9).
SURVIVOR_DEDUCTIBLE_CENTS = 50000
SPOUSE_SHARE_RATE_NUM = 20   # 0.20
SPOUSE_SHARE_RATE_DEN = 100
CHILD_SHARE_RATE_NUM = 30    # 0.30
CHILD_SHARE_RATE_DEN = 100
SPOUSE_MONTHS = 3
CHILD_MONTHS = 2

# Product availability matrix (PRD §3.7).
FACET_GROUPS = ("BANKING", "INSURANCE", "INVESTMENT", "DEPLOYMENT")
FACETS_PER_GROUP = 6

# All six eligibility categories, for "open to everyone" offerings.
ALL_CATEGORIES = [
    "OFFICER_CADET",
    "ENLISTED_ACTIVE",
    "VETERAN_HONORABLE",
    "FAMILY_SPOUSE",
    "FAMILY_WIDOW",
    "FAMILY_CHILD",
]
