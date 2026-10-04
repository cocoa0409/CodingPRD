"""Domain constants — every value below is pinned verbatim in PRD.md."""

# Logical clock (PRD §2.5): "the logical clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# Safety-test action levels (PRD §3.2)
LEAD_LIMIT_PPM = 2.00          # ADULTERANT_SCREEN: FAIL when measured_value >= 2.00
PESTICIDE_LIMIT_PPM = 0.10     # PESTICIDE: FAIL when measured_value >= 0.10
MICRO_LIMIT_CFU_G = 100000     # MICRO: FAIL when measured_value > 100000 (at-limit PASS)
MOISTURE_LIMIT_PCT = 12.0      # MOISTURE: FAIL when measured_value > 12.0 (at-limit PASS)

# Required acceptance suite (PRD §3.2): MICRO, ADULTERANT_SCREEN, MOISTURE
REQUIRED_TEST_SUITE = ["MICRO", "ADULTERANT_SCREEN", "MOISTURE"]

# Blend formula defaults (PRD §3.3)
FLAVOR_TOLERANCE_PCT_DEFAULT = 2.0
MAX_MOISTURE_PCT_DEFAULT = 10.0

# Formula activation proportion gate (PRD §3.3): within 0.01 of the 100.0 target
PROPORTION_SUM_TARGET = 100.0
PROPORTION_SUM_EPSILON = 0.01

# Blend sourcing (PRD §3.4): single-lot cap is 40.0 percent of needed kg
MAX_SINGLE_LOT_SHARE_PCT = 40.0
ALLOCATION_QTY_DECIMALS = 3

# Finished-batch shelf life (PRD §3.6)
SHELF_LIFE_DAYS = 540
MIN_SHIP_REMAINING_SHELF_LIFE_PCT = 75.0
# PRD §3.6: "a batch with exactly 405 days remaining sits exactly at 75.0 percent"
SHIP_BOUNDARY_DAYS = 405

# Weekly capacity pool (PRD §3.5): capacity_kg_per_shift * 5 shifts * surge multiplier
SHIFTS_PER_WEEK = 5
SURGE_WEEK_START = 44
SURGE_WEEK_END = 52
SURGE_CAPACITY_MULTIPLIER = 1.25

# Cost rollup overhead (PRD §3.4): subtotal multiplied by 3.5 percent
PRODUCTION_OVERHEAD_PCT = 3.5

# Lot receiving (PRD §3.1): crop_year between 2000 and 2100 inclusive
CROP_YEAR_MIN = 2000
CROP_YEAR_MAX = 2100

# Enums declared in PRD §3.1 / §3.5
SPICE_CODES = ["BLACK_PEPPER", "PAPRIKA", "CUMIN", "OREGANO", "GARLIC_POWDER", "CINNAMON"]
ALLERGEN_PROFILES = ["NONE", "CELERY", "MUSTARD", "SESAME", "GLUTEN"]
CHANGEOVER_CLASSES = ["NONE", "DRY_CLEAN", "WET_WASH", "FULL_SANITATION"]
CERTIFICATIONS = ["ORGANIC", "KOSHER", "HALAL", "NON_GMO"]

# Masked supplier view (PRD §2.10): prefix CMP- followed by a letter in creation order
MASKED_CODE_PREFIX = "CMP-"

# Role catalog (PRD §2.1)
ROLES = [
    "PlatformAdmin",
    "SupplyPlanner",
    "QualityAnalyst",
    "QualityManager",
    "FlavorScientist",
    "ProductionScheduler",
    "RecallCoordinator",
    "SupplierRep",
]
