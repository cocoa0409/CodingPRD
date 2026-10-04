"""Domain constants — every value pinned by PRD.md.

Sources (PRD.md):
- §2.5 logical clock startup default and lazy windows
- §3.3 order pricing tiers and delivery fee
- §3.5 freshness pull threshold / window
- §3.6 training coverage minimums, certification validity, visit spacing
- §3.7 promo brand share and regulatory floor
- §3.9 performance score weights and window
"""
from decimal import Decimal, ROUND_HALF_UP

# --- Logical clock (PRD §2.5) ---
CLOCK_STARTUP_DEFAULT_ISO = "2026-09-01T00:00:00Z"
TERRITORY_COOLING_OFF_DAYS = 30

# --- Freshness / pull discipline (PRD §3.5) ---
LATE_PULL_SUSPENSION_THRESHOLD = 3
LATE_PULL_WINDOW_DAYS = 30
ALLERGEN_CLEANING_WINDOW_HOURS = 24

# --- Training coverage (PRD §3.6) ---
TRAINING_MIN_CERTS = 2
CERT_VALIDITY_DAYS = 180

# --- Service visit spacing (PRD §3.6) ---
VISIT_MIN_GAP_MINUTES = 30

# --- Promo fiscal constants (PRD §3.7) ---
PROMO_BRAND_SHARE = 0.6
PROMO_FLOOR_PCT = 0.85

# --- Order pricing tiers (PRD §3.3) ---
TIER1_THRESHOLD_CENTS = 500000
TIER1_PCT = 0.08
TIER2_THRESHOLD_CENTS = 200000
TIER2_PCT = 0.05
TIER3_THRESHOLD_CENTS = 100000
TIER3_PCT = 0.02
FREE_DELIVERY_THRESHOLD_CENTS = 100000
DELIVERY_FEE_CENTS = 1500

# --- Allocation waterfall priority (PRD §3.3) ---
TIER_RANK = {"ELITE": 0, "PREFERRED": 1, "STANDARD": 2}

# --- Distributor performance scoring (PRD §3.9) ---
PERF_W_VISIT = 0.5
PERF_W_PULL = 0.3
PERF_W_FILL = 0.2
PERFORMANCE_WINDOW_DAYS = 90

# --- Common fixture defaults ---
DEFAULT_DELIVERY_WEEK = "2026-09-07"  # a Monday
DEFAULT_RUN_WINDOW_START = "2026-09-01T06:00:00Z"
DEFAULT_RUN_WINDOW_END = "2026-09-01T12:00:00Z"
DEFAULT_VISIT_WINDOW_START = "2026-09-02T09:00:00Z"
DEFAULT_VISIT_WINDOW_END = "2026-09-02T10:00:00Z"
DEFAULT_PROMO_START_DATE = "2026-10-01"
DEFAULT_PROMO_END_DATE = "2026-10-07"


def round_half_up(value, ndigits=0):
    """PRD §2.7: wherever a calculation rounds, it rounds half up."""
    quant = Decimal(1) if ndigits == 0 else Decimal(1).scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def promo_floor_cents(base_price_cents):
    """PRD §3.7: regulatory floor = round_half_up(base_price_cents * 0.85, 0)."""
    return int(round_half_up(base_price_cents * PROMO_FLOOR_PCT, 0))


def promo_unit_allowance_cents(base_price_cents, promo_price_cents):
    """PRD §3.7: round_half_up((base - promo) * 0.6, 0)."""
    return int(round_half_up((base_price_cents - promo_price_cents) * PROMO_BRAND_SHARE, 0))


def promo_settlement_line_cents(units, base_price_cents, promo_price_cents):
    """PRD §3.7: per-line round_half_up(units * markdown * 0.6, 0)."""
    markdown = base_price_cents - promo_price_cents
    return int(round_half_up(units * markdown * PROMO_BRAND_SHARE, 0))


def expected_order_pricing(merchandise_total_cents):
    """PRD §3.3 pinned order: tier on pre-discount, fee on post-discount.

    Returns (discount_cents, delivery_fee_cents, total_cents).
    """
    if merchandise_total_cents >= TIER1_THRESHOLD_CENTS:
        tier_pct = TIER1_PCT
    elif merchandise_total_cents >= TIER2_THRESHOLD_CENTS:
        tier_pct = TIER2_PCT
    elif merchandise_total_cents >= TIER3_THRESHOLD_CENTS:
        tier_pct = TIER3_PCT
    else:
        tier_pct = 0.0
    discount = int(round_half_up(merchandise_total_cents * tier_pct, 0))
    fee = 0 if (merchandise_total_cents - discount) >= FREE_DELIVERY_THRESHOLD_CENTS else DELIVERY_FEE_CENTS
    total = merchandise_total_cents - discount + fee
    return discount, fee, total
