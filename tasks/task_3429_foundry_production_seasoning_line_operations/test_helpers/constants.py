"""Domain constants — every literal cross-checked against the PRD.

PRD section citations accompany each group. These are the values the
calculations and gates use; tests should import them rather than re-typing
literals.
"""
from decimal import Decimal, ROUND_HALF_UP

# --- Logical clock (PRD §2.4) -------------------------------------------------
# "Before any clock-advance call has been made, the logical clock reads
# exactly 2026-09-01T00:00:00Z."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Pagination (PRD §2.3) ----------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Melt charge component prices, cents per lb (PRD §3.3) --------------------
PIG_IRON_CENTS_PER_LB = 38
SCRAP_STEEL_CENTS_PER_LB = 12
RETURNS_CENTS_PER_LB = 6
ALLOY_CENTS_PER_LB = 145

# Planned mix percentages must sum to 100.0 within this tolerance (PRD §3.3).
CHARGE_MIX_SUM = 100.0
CHARGE_MIX_SUM_TOLERANCE = 0.01

# --- Chemistry certification gate (PRD §3.3) ----------------------------------
CE_MIN = 3.90
CE_MAX = 4.30          # inclusive: exactly 4.30 passes, 4.31 fails
SULFUR_MAX = 0.060
PHOSPHORUS_MAX = 0.080
BATH_TEMP_MIN_F = 2650

# --- Iron mass ledger (PRD §3.3) ----------------------------------------------
SLAG_LOSS_PCT = 0.03   # slag_loss_lbs = round_half_up(tapped_lbs * 0.03, 2)
OZ_PER_LB = 16.0       # pour weight conversion: pour_total_lbs = oz / 16.0

# --- Unit cost economics (PRD §3.2) -------------------------------------------
STD_CONVERSION_CENTS_PER_UNIT = 1450
LABOR_RATE_CENTS_PER_HOUR = 3200
ENERGY_RATE_CENTS_PER_KWH = 14
OVERHEAD_CENTS_PER_POURED_UNIT = 185
MARGIN_MIN_PCT = 0.30  # margin_flag true when margin < 0.30

# --- Yield gate at completion (PRD §3.2) --------------------------------------
# good_units >= ceil(0.85 * planned_quantity)
MIN_YIELD_RATIO = 0.85

# --- Scrap tiering and posture (PRD §2.8) -------------------------------------
SCRAP_WATCH_THRESHOLD = 0.04     # scrap_index >= 0.04 -> WATCH (inclusive)
SCRAP_RESTRICT_THRESHOLD = 0.08  # scrap_index >= 0.08 -> RED (inclusive)
REWORK_SCRAP_WEIGHT = 1.5        # unit scrapped after >= 1 rework
PLAIN_SCRAP_WEIGHT = 1.0         # unit scrapped never reworked
SCRAP_INDEX_DECIMALS = 4

# --- Rework cap (PRD §3.5) ----------------------------------------------------
MAX_REWORK_COUNT = 2  # the third REWORK disposition is rejected

# --- Pour limits (PRD §3.4) ---------------------------------------------------
POUR_MIN_UNITS = 1
POUR_MAX_UNITS = 48  # unit_count in 1..48

# --- Sand mix rules (PRD §3.4) ------------------------------------------------
RECLAIMED_SAND_MAX_PCT = 85.0
MOISTURE_MIN_PCT = 3.0
MOISTURE_MAX_PCT = 4.5
CLAY_MIN_PCT = 8.0
CLAY_MAX_PCT = 12.0
SAND_MIX_SUM = 100.0
SAND_MIX_SUM_TOLERANCE = 0.01
SAND_LOSS_MAX_PCT = 0.12  # reclaim loss <= 12% of sand weight (inclusive)

# --- Sand reclamation permit rate (PRD §3.4, §3.7) -----------------------------
SAND_RATE_BREACH_MARGIN = 0.05  # rate < limit - 0.05 -> BREACH
SAND_RATE_DECIMALS = 4

# --- Emissions accounting (PRD §3.7) -------------------------------------------
BREACH_MULTIPLIER = 1.5  # single reading >= 1.5 * limit -> immediate BREACH
OVER_LIMIT_BREACH_COUNT = 2  # second over-limit reading in a month -> BREACH

# --- Seasoning line (PRD §3.6) -------------------------------------------------
OVEN_ID = "OVEN_1"
OVEN_CAPACITY_UNITS = 12
SEASONING_MAX_UNITS = 12
COATING_COUNT_MIN = 1
COATING_COUNT_MAX = 3
CURE_RELEASE_THRESHOLD = 70  # RELEASE requires cure_score >= 70
CURE_SCORE_TEMP_WEIGHT = 60
CURE_SCORE_DURATION_WEIGHT = 40
DURATION_FACTOR_CAP = 1.5

# Cure profiles per oil: (MIN_TEMP_F, MAX_TEMP_F, MIN_MINUTES)
CURE_PROFILES = {
    "SOYBEAN": {"min_temp_f": 450, "max_temp_f": 500, "min_minutes": 60},
    "CANOLA": {"min_temp_f": 425, "max_temp_f": 475, "min_minutes": 75},
    "FLAXSEED": {"min_temp_f": 400, "max_temp_f": 450, "min_minutes": 90},
}

# --- Seasonal channel split (PRD §3.8) -----------------------------------------
# Pinned waterfall order: museum store, factory outlet, ecommerce, retail chain.
MUSEUM_STORE_PCT = 0.02
FACTORY_OUTLET_PCT = 0.08
ECOMMERCE_PCT = 0.15

# --- Pricing floors (PRD §3.1, §3.8) -------------------------------------------
BRAND_FLOOR_MULTIPLIER = 1.15       # wholesale >= round_half_up(import * 1.15)
FACTORY_OUTLET_FLOOR_PCT = 0.55     # outlet floor = round_half_up(msrp * 0.55)
MUSEUM_STORE_FLOOR_PCT = 1.0        # museum floor = msrp

# --- Peak-window allocation freeze (PRD §3.8) ----------------------------------
ALLOCATION_FREEZE_DAYS = 42  # freeze starts 42 days before ship_week (inclusive)

# --- Scheduled week bounds (PRD §3.2) ------------------------------------------
WEEK_MIN = 1
WEEK_MAX = 53


def round_half_up(value, ndigits=0):
    """Round half-up to `ndigits` decimal places using Decimal (PRD §2.7)."""
    quant = Decimal(1) if ndigits == 0 else Decimal(1).scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    """Round half-up to an integer (PRD §2.7: monetary amounts are integer cents)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
