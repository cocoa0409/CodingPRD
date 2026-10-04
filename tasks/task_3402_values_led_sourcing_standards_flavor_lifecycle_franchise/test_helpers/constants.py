"""Domain thresholds and constants — values pinned by the PRD (§2.3, §2.5, §2.10, §3)."""

# Logical clock (PRD §2.5): server default before any client call.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Premium tier bounds (PRD §3.3): below 60 -> 0%; [60,75) -> 5%; [75,90) -> 8%; >=90 -> 12%.
TIER1_MIN_SCORE = 60
TIER1_PCT = 5
TIER2_MIN_SCORE = 75
TIER2_PCT = 8
TIER3_MIN_SCORE = 90
TIER3_PCT = 12
NON_CONFORMANCE_DEDUCTION_PCT = 2   # percentage points per non-conformance
EXCESS_VOLUME_BONUS_PCT = 1         # marginal excess bonus over the effective pct

# Audit composite (PRD §3.2).
WEIGHT_LABOR = 0.4
WEIGHT_ENVIRONMENT = 0.3
WEIGHT_COMMUNITY = 0.3
PASS_COMPOSITE_MIN = 70
PASS_MAX_FINDINGS = 2

# Claim publish coverage thresholds (PRD §3.5).
CLAIM_COVERAGE_THRESHOLD = {
    "FAIR_TRADE_SOURCING": 95,
    "ORGANIC_INGREDIENTS": 100,
    "NON_GMO": 90,
    "CLIMATE_POSITIVE": 100,
}

# Plant-shift capacity-unit pool (PRD §2.10 / §3.4).
PLANT_SHIFT_CAPACITY_UNITS = {
    "VT_WATERBURY": 1000,
    "VT_ST_ALBANS": 800,
    "NL_HELLENDOORN": 600,
}
CHUNK_HEAVY_THRESHOLD_PCT = 20
CHUNK_FACTOR = 1.5
SWIRL_HEAVY_THRESHOLD_PCT = 15
SWIRL_FACTOR = 1.25

# Plant-day pint pool for supply-order allocation (PRD §2.10 / §3.8).
PLANT_DAY_ORDER_CAPACITY_PINTS = {
    "VT_WATERBURY": 12000,
    "VT_ST_ALBANS": 9000,
    "NL_HELLENDOORN": 7000,
}

# Supply-order pricing (PRD §3.8).
PARTNER_DISCOUNT_PCT = 0.15

# Scoop shop fees (PRD §3.8).
FRANCHISE_FEE_CENTS = 3_500_000
PARTNER_FEE_CENTS = 0

# Revival (PRD §3.6).
REVIVAL_SIGNATURE_THRESHOLD = 500
REVIVAL_WINDOW_DAYS = 730

# Pagination (PRD §2.3).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
