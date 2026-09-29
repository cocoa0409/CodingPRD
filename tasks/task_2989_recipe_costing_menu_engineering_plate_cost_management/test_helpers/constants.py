"""Domain constants pinned by the PRD.

Every value here is a literal the PRD states outright; nothing is derived by
guesswork.  Money is always an integer count of micros or cents, ratios are
always integer basis points.
"""

# ─── API mount point ──────────────────────────────────

BASE = "/culinary"

# ─── Integer arithmetic scales (PRD 2.5) ──────────────

MICROS_PER_USD = 1_000_000
MICROS_PER_CENT = 10_000
BPS_WHOLE = 10_000
BPS_PER_PERCENT = 100
MICRO_KCAL_PER_KCAL = 1_000_000

# ─── The logical clock (PRD 2.4) ──────────────────────

CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# ─── Regional parameters (PRD 2.8) ────────────────────

REGION_CODES = ("NE", "SE", "MW", "WEST")

REGION_FREIGHT_UPLIFT_BPS = {"NE": 600, "SE": 250, "MW": 0, "WEST": 450}
REGION_CAP_MULTIPLIER_BPS = {"NE": 11500, "SE": 10500, "MW": 11000, "WEST": 12000}
REGION_COMPETITOR_INDEX_CENTS = {"NE": 1750, "SE": 1450, "MW": 1500, "WEST": 1900}

REFERENCE_REGION_CODE = "MW"

# ─── Allergen bit positions (PRD 2.9) ─────────────────

ALLERGEN_MILK = 1
ALLERGEN_EGG = 2
ALLERGEN_GLUTEN = 4
ALLERGEN_PEANUT = 8
ALLERGEN_SOY = 16
ALLERGEN_FISH = 32
ALLERGEN_SHELLFISH = 64
ALLERGEN_TREE_NUT = 128
ALLERGEN_MASK_MAX = 255

# ─── Recipe graph limits (PRD 3.3) ────────────────────

MAX_RECIPE_DEPTH = 4

# ─── Plate costing (PRD 3.5) ──────────────────────────

WASTE_FACTOR_BPS = 10_200
GARNISH_ALLOWANCE_BPS = 150
GARNISH_FLOOR_MICROS = 8_000

# ─── Menu item activation limits (PRD 3.5) ────────────

KIDS_MENU_SODIUM_CAP_MCG_PER_PORTION = 640_000
TARGET_FOOD_COST_BPS_MIN = 500
TARGET_FOOD_COST_BPS_MAX = 9_000

# ─── Price change proposals (PRD 3.7) ─────────────────

PRICE_CHANGE_COOLING_OFF_DAYS = 14
MARGIN_FLOOR_CENTS = 300
CURRENT_PRICE_CAP_MULTIPLIER_BPS = 11_200
FOOD_COST_RELIEF_BPS = 300
MAX_REVISION_ROUNDS = 2
DEFAULT_BASELINE_UNITS = 1_000
ELASTICITY_BPS_MIN = 0
ELASTICITY_BPS_MAX = 50_000

# ─── Cost roll-up bases (PRD 3.3) ─────────────────────

WEIGHTED_AVG_WINDOW_DAYS = 90
WEIGHTED_AVG_PACK_BASE_UNITS_SNAPSHOT = 1_000_000

# ─── Period reviews (PRD 3.8) ─────────────────────────

POPULARITY_THRESHOLD_NUMERATOR_BPS = 7_000
VARIANCE_TOLERANCE_BPS = 300

# ─── Limited-time offers (PRD 3.9) ────────────────────

PROMO_SUPPORT_RATE_BPS = 300
LTO_ATTAINMENT_THRESHOLD_BPS = 8_000
LTO_MAX_OVERLAPPING_LAUNCHED_PER_REGION = 2

# ─── Pagination (PRD 2.3) ─────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Identifiers that resolve to nothing ──────────────

MISSING_UUID = "00000000-0000-4000-8000-000000000000"
MISSING_UUID_ALT = "00000000-0000-4000-8000-000000000001"
MISSING_UUID_BEEF = "00000000-0000-4000-8000-00000000beef"

# ─── String field bounds (PRD 3.1, 3.3, 3.5) ──────────

UNIT_CODE_MIN_LEN = 3
UNIT_CODE_MAX_LEN = 12
SKU_MIN_LEN = 3
SKU_MAX_LEN = 20
RECIPE_CODE_MIN_LEN = 3
RECIPE_CODE_MAX_LEN = 20
NAME_MAX_LEN = 80
