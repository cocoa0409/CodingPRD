"""Domain constants for the Packaging Extended Producer Responsibility API.

Every value here is taken verbatim from the PRD narrative (thresholds, ladders,
rounding rules, default clock) or is a shared fixture literal used to build
preconditions through the PRD's own endpoints.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_Z = "2026-08-01T00:00:00Z"

# Clock used by the deep-behaviour chains.
CLOCK_2026_09_01 = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Eco-modulation constants (PRD 3.8)
# ---------------------------------------------------------------------------
MALUS_READILY_RECYCLABLE_PCT = 0
MALUS_LIMITED_PCT = 20
MALUS_NOT_RECYCLABLE_PCT = 60
PCR_BONUS_STEP_PCT = 5
PCR_BONUS_CAP_PCT = 25
REUSE_BONUS_PCT = 15
NET_PCT_FLOOR = -30
NET_PCT_CEILING = 60

# ---------------------------------------------------------------------------
# Membership fee constants (PRD 3.6)
# ---------------------------------------------------------------------------
MEMBERSHIP_FREE_TONNAGE_KG = 500
MEMBERSHIP_SURCHARGE_PER_1000KG_CENTS = 50000

# ---------------------------------------------------------------------------
# Invoice administrative fee (PRD 3.9)
# ---------------------------------------------------------------------------
ADMIN_TIER_BREAK_CENTS = 40000

# ---------------------------------------------------------------------------
# Verification capacity (PRD 2.11 / 3.7)
# ---------------------------------------------------------------------------
VERIFIER_BUFFER_DAYS = 2
VERIFIER_MAX_CONCURRENT_ENGAGEMENTS = 2

# ---------------------------------------------------------------------------
# Enumerations reachable from request bodies
# ---------------------------------------------------------------------------
PRODUCT_CATEGORIES = [
    "BEVERAGE",
    "FOOD_DRY",
    "HOUSEHOLD_CHEM",
    "MEDICAL_DEVICE",
    "PERSONAL_CARE",
]
MATERIAL_TYPES = ["PLASTIC", "PAPER", "GLASS", "METAL"]
RECYCLABILITY_CLASSES = ["READILY_RECYCLABLE", "LIMITED", "NOT_RECYCLABLE"]

# ---------------------------------------------------------------------------
# Shared fee schedule rate bands
# ---------------------------------------------------------------------------
# Tiered bands covering all four materials, used by the deep pricing chains.
TIERED_MATERIAL_RATES = [
    {"material_type": "PLASTIC", "tier_min_kg": 0, "tier_max_kg": 1000, "rate_cents_per_kg": 42},
    {"material_type": "PLASTIC", "tier_min_kg": 1000, "tier_max_kg": 5000, "rate_cents_per_kg": 33},
    {"material_type": "PLASTIC", "tier_min_kg": 5000, "tier_max_kg": None, "rate_cents_per_kg": 25},
    {"material_type": "PAPER", "tier_min_kg": 0, "tier_max_kg": 1000, "rate_cents_per_kg": 18},
    {"material_type": "PAPER", "tier_min_kg": 1000, "tier_max_kg": None, "rate_cents_per_kg": 12},
    {"material_type": "GLASS", "tier_min_kg": 0, "tier_max_kg": None, "rate_cents_per_kg": 9},
    {"material_type": "METAL", "tier_min_kg": 0, "tier_max_kg": None, "rate_cents_per_kg": 15},
]

# A single open-ended GLASS band at 9 cents per kilogram.
GLASS_ONLY_RATES = [
    {"material_type": "GLASS", "tier_min_kg": 0, "tier_max_kg": None, "rate_cents_per_kg": 9},
]

BASE_MEMBERSHIP_FEE_CENTS = 250000
ADMIN_FEE_BPS_LOW = 500
ADMIN_FEE_BPS_HIGH_DEEP = 300
ADMIN_FEE_BPS_HIGH_BREADTH = 900

# ---------------------------------------------------------------------------
# Small-producer thresholds used by the two program flavours
# ---------------------------------------------------------------------------
DEEP_REVENUE_THRESHOLD_USD = 5000000
DEEP_TONNAGE_THRESHOLD_KG = 1000
BREADTH_REVENUE_THRESHOLD_USD = 1000000
BREADTH_TONNAGE_THRESHOLD_KG = 1.0

REGISTRATION_DEADLINE_DEFAULT = "2026-12-31T23:59:59Z"

# ---------------------------------------------------------------------------
# The GLASS-mini stock keeping unit: one 50.00 g GLASS component at 110 units,
# which weighs 5.500 kg and prices to 49.5000 exact cents / 50 whole cents.
# ---------------------------------------------------------------------------
GLASS_MINI_UNIT_WEIGHT_GRAMS = 50.0
GLASS_MINI_UNITS = 110
GLASS_MINI_WEIGHT_KG = 5.500
GLASS_MINI_LINE_FEE_EXACT_CENTS = 49.5000
GLASS_MINI_LINE_FEE_CENTS = 50
GLASS_MINI_ADMIN_FEE_CENTS = 3
GLASS_MINI_INVOICE_TOTAL_CENTS = 53
