"""PRD-named constants. Each constant is defined exactly once, here."""
from decimal import Decimal

# --- Logical clock (PRD 2.4) ---
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Pricing engine (PRD 3.3) ---
INTERRUPTIBLE_DISCOUNT_PCT = Decimal("0.25")
LOSS_FACTOR = Decimal("1.037")

# --- Curtailment margin gate (PRD 3.5) ---
ALUMINA_RATIO_T_PER_T = Decimal("1.92")
POWER_INTENSITY_MWH_PER_T = Decimal("13.5")
OTHER_CONVERSION_COST_PER_T = Decimal("420.0")
RESTART_RESERVE_PER_T = Decimal("150.0")

# --- Restart cost schedule (PRD 3.6) ---
RESTART_CREW_COST_PER_DAY = 15000
WARM_THRESHOLD_HOURS = 24
COLD_THRESHOLD_HOURS = 720
RESTART_CLASS_SCHEDULE = {
    "HOT": {"base": 80000, "per_tpd": 40, "per_idle_day": 0},
    "WARM": {"base": 350000, "per_tpd": 120, "per_idle_day": 2500},
    "COLD": {"base": 1800000, "per_tpd": 400, "per_idle_day": 6000},
}

# --- Hedging (PRD 3.7) ---
HEDGE_MIN_COVERAGE = Decimal("0.5")
MONTHLY_CAPACITY_DAYS = 30

# --- Power contracts (PRD 3.2) ---
DEFAULT_TAKE_OR_PAY_PCT = Decimal("0.9")
CONTRACT_YEAR_DAYS = 365

# --- Product mix (PRD 3.9) ---
BILLET_CONVERSION_PER_T = Decimal("180.0")
SLAB_CONVERSION_PER_T = Decimal("220.0")
VALUE_ADDED_CONVERSION_PER_T = Decimal("350.0")
VA_PREMIUM_TIER_LOW = Decimal("120")
VA_PREMIUM_TIER_MID = Decimal("180")
VA_PREMIUM_TIER_HIGH = Decimal("240")
VA_SHARE_TIER1_MAX = Decimal("0.10")
VA_SHARE_TIER2_MAX = Decimal("0.25")

# --- RBAC (PRD 2.1) ---
ROLES = (
    "PlatformAdmin",
    "EnergyManager",
    "TradingAnalyst",
    "SmelterManager",
    "Controller",
    "VPOperations",
    "EHSManager",
)

# --- Enums ---
REGION_CODES = ("NA_NORTHWEST", "NA_MIDWEST", "EU_NORDIC", "AU_EAST")
GLOBAL_REGION = "GLOBAL"
INSTRUMENTS = ("POWER_SPOT", "ALUMINUM_LME", "REGIONAL_PREMIUM", "ALUMINA_INDEX")
REGIONAL_INSTRUMENTS = ("POWER_SPOT", "REGIONAL_PREMIUM")
HEDGE_INSTRUMENTS = ("LME_SWAP", "PREMIUM_SWAP")
COMPONENT_TYPES = ("FIXED", "MARKET_INDEXED", "INTERRUPTIBLE")
TRIGGER_TYPES = ("POWER_PRICE", "METAL_PRICE", "GRID_EMERGENCY", "MAINTENANCE")
PRICING_MODELS = ("COST_PLUS", "MARKET_LINKED")
PERMIT_TYPES = ("EMISSIONS", "SPL_DISPOSAL")
PRODUCT_FORMS = ("BILLET", "SLAB", "VALUE_ADDED")

# --- Pagination (scaffold response_envelope / PRD 2.3) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
