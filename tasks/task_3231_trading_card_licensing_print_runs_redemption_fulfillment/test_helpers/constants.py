"""Domain thresholds — numeric constants named in the PRD prose."""

# PRD §3.2 — the platform's standard set size, stated in prose as 100 cards.
CARDS_PER_SET = 100

# PRD §3.3 — projection constants, all given with the rule that consumes them.
SALES_HISTORY_UNITS_PER_CLAIM = 1000
SALES_HISTORY_MIN_RECORDS = 3
MARKET_DEMAND_UNITS_PER_CASE = 10
CLAIM_BACKDATE_WINDOW_DAYS = 30

PROJECTION_FLOOR = {"BASE": 1000, "INSERT": 100, "PREMIUM": 25}
PROJECTION_CEILING = {"BASE": 50000, "INSERT": 10000, "PREMIUM": 2000}
PROJECTION_MULTIPLE_OF = {"BASE": 500, "INSERT": 100, "PREMIUM": 25}
BRAND_DIRECTIVE_BASE = {"BASE": 12000, "INSERT": 3000, "PREMIUM": 400}

# PRD §3.3 — defect-evidence safety floor.
REORDER_HIT_RATE = 0.005

# PRD §3.7 — severity weights.
SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}

# PRD §3.4 — signer royalty, charged per allocation line.
SIGNER_ROYALTY_CENTS = 750

# PRD §3.5 — substitution policy.
SUBSTITUTION_DIVERGENCE_CENTS = 250000
SUBSTITUTION_RATIO_LOW = 1.00
SUBSTITUTION_RATIO_HIGH = 1.25
SUBSTITUTION_DEADLINE_DAYS_LOW = 365
SUBSTITUTION_DEADLINE_DAYS_HIGH = 730

# PRD §2.3 — pagination.
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# PRD §2.4 — the logical clock never falls back to real time.
CLOCK_START = "2026-09-01T00:00:00Z"

# Handy scenario anchors used across the suite.
LICENSE_ACTIVE_START = "2026-01-01T00:00:00Z"
LICENSE_ACTIVE_END = "2029-12-31T00:00:00Z"
DEFAULT_APPROVAL_WINDOW_DAYS = 10
DEFAULT_SIGNER_NAME = "Ken Griffey Jr"

# A well-formed configuration: boxes_per_case * packs_per_box * cards_per_pack
# is 20 * 10 * 10 = 2000, an exact multiple of the standard set size.
DEFAULT_BOX_CONFIG = {
    "packs_per_box": 10,
    "cards_per_pack": 10,
    "boxes_per_case": 20,
}
DEFAULT_SETS_PER_CASE = 2000
DEFAULT_CASES_PRINTED = 50
DEFAULT_RUN_PLANNED_ON = "2026-10-01T00:00:00Z"