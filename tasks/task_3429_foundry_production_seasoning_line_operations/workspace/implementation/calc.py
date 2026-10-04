"""All PRD calculations with exact constants, rounding (half-up) and bounds."""
import math
from decimal import Decimal, ROUND_HALF_UP

# carbon_equivalent
CE_MIN = Decimal("3.90")
CE_MAX = Decimal("4.30")
SULFUR_MAX = Decimal("0.060")
PHOSPHORUS_MAX = Decimal("0.080")
BATH_TEMP_MIN_F = Decimal("2650")

# melt_charge_cost component prices (cents per lb)
PIG_IRON_CENTS_PER_LB = 38
SCRAP_STEEL_CENTS_PER_LB = 12
RETURNS_CENTS_PER_LB = 6
ALLOY_CENTS_PER_LB = 145

# unit_cost
STD_CONVERSION_CENTS_PER_UNIT = 1450
LABOR_RATE_CENTS_PER_HOUR = 3200
ENERGY_RATE_CENTS_PER_KWH = 14
OVERHEAD_CENTS_PER_POURED_UNIT = 185
MARGIN_MIN_PCT = Decimal("0.30")

# scrap_index / tiering
REWORK_SCRAP_WEIGHT = Decimal("1.5")
SCRAP_WATCH_THRESHOLD = Decimal("0.04")
SCRAP_RESTRICT_THRESHOLD = Decimal("0.08")
MAX_REWORK_COUNT = 2

# emissions_period_rollup / sand_reclamation_rate
BREACH_MULTIPLIER = Decimal("1.5")
SAND_RATE_BREACH_MARGIN = Decimal("0.05")
SAND_LOSS_MAX_PCT = Decimal("0.12")

# iron_mass_ledger
SLAG_LOSS_PCT = Decimal("0.03")

# cure_score
CURE_RELEASE_THRESHOLD = 70
CURE_PROFILES = {
    "SOYBEAN": {"min_temp": Decimal("450"), "max_temp": Decimal("500"), "min_minutes": 60},
    "CANOLA": {"min_temp": Decimal("425"), "max_temp": Decimal("475"), "min_minutes": 75},
    "FLAXSEED": {"min_temp": Decimal("400"), "max_temp": Decimal("450"), "min_minutes": 90},
}

# channel_allocation_split
MUSEUM_STORE_PCT = Decimal("0.02")
FACTORY_OUTLET_PCT = Decimal("0.08")
ECOMMERCE_PCT = Decimal("0.15")
OVEN_CAPACITY = 12

# product / outlet pricing
BRAND_FLOOR_MULT = Decimal("1.15")
OUTLET_FLOOR_PCT = Decimal("0.55")

# order completion yield
COMPLETE_YIELD_MIN = Decimal("0.85")

# allocation peak freeze
ALLOCATION_FREEZE_DAYS = 42


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x, places):
    """Round-half-up to `places` decimal places, returning Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return D(x).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(x):
    """Round-half-up to integer, returning int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def carbon_equivalent(carbon_pct, silicon_pct, phosphorus_pct):
    return rhu(D(carbon_pct) + (D(silicon_pct) + D(phosphorus_pct)) / Decimal("3.0"), 2)


def chemistry_in_spec(ce, sulfur_pct, phosphorus_pct, bath_temp_f):
    return (
        CE_MIN <= D(ce) <= CE_MAX
        and D(sulfur_pct) <= SULFUR_MAX
        and D(phosphorus_pct) <= PHOSPHORUS_MAX
        and D(bath_temp_f) >= BATH_TEMP_MIN_F
    )


def planned_charge_cost_cents(iron_lbs, pig_pct, scrap_pct, returns_pct, alloy_pct):
    """Single rounding over the whole weighted planned mix."""
    weighted = (
        D(pig_pct) * PIG_IRON_CENTS_PER_LB
        + D(scrap_pct) * SCRAP_STEEL_CENTS_PER_LB
        + D(returns_pct) * RETURNS_CENTS_PER_LB
        + D(alloy_pct) * ALLOY_CENTS_PER_LB
    )
    return rhu_int(D(iron_lbs) * weighted / Decimal("100"))


def charge_call_cost_cents(pig_lbs, scrap_lbs, returns_lbs, alloy_lbs):
    """Per-component-line rounding FIRST, then sum the integer lines (pinned order)."""
    return (
        rhu_int(D(pig_lbs) * PIG_IRON_CENTS_PER_LB)
        + rhu_int(D(scrap_lbs) * SCRAP_STEEL_CENTS_PER_LB)
        + rhu_int(D(returns_lbs) * RETURNS_CENTS_PER_LB)
        + rhu_int(D(alloy_lbs) * ALLOY_CENTS_PER_LB)
    )


def slag_loss_lbs(tapped_lbs):
    return rhu(D(tapped_lbs) * SLAG_LOSS_PCT, 2)


def pour_total_lbs(unit_count, pour_weight_per_unit_oz):
    # division by 16 terminates in decimal; no rounding specified for the total
    return D(unit_count) * D(pour_weight_per_unit_oz) / Decimal("16")


def returns_credit_for_unit(pour_weight_oz):
    return rhu(D(pour_weight_oz) / Decimal("16"), 2)


def scrap_index(scrap_weighted_units, poured_units):
    if poured_units == 0:
        return Decimal("0")
    return rhu(D(scrap_weighted_units) / D(poured_units), 4)


def scrap_tier(idx):
    idx = D(idx)
    if idx >= SCRAP_RESTRICT_THRESHOLD:
        return "RED"
    if idx >= SCRAP_WATCH_THRESHOLD:
        return "WATCH"
    return "GREEN"


def unit_cost_provisional(material_to_date_cents, planned_quantity):
    return rhu_int(D(material_to_date_cents) / D(planned_quantity)) + STD_CONVERSION_CENTS_PER_UNIT


def unit_cost_final(material_cents, labor_hours, energy_kwh, poured_units, good_units):
    labor = rhu_int(D(labor_hours) * LABOR_RATE_CENTS_PER_HOUR)
    energy = rhu_int(D(energy_kwh) * ENERGY_RATE_CENTS_PER_KWH)
    overhead = OVERHEAD_CENTS_PER_POURED_UNIT * poured_units
    total = material_cents + labor + energy + overhead
    return rhu_int(D(total) / D(good_units))


def margin_flag(wholesale_price_cents, unit_cost_final_cents):
    return (
        D(wholesale_price_cents) - D(unit_cost_final_cents)
    ) / D(wholesale_price_cents) < MARGIN_MIN_PCT


def min_good_units(planned_quantity):
    return math.ceil(COMPLETE_YIELD_MIN * planned_quantity)


def channel_allocation_split(build_qty):
    """Pinned waterfall order: museum, outlet, ecommerce, then retail absorbs rest."""
    n = D(build_qty)
    remaining = int(build_qty)
    museum = min(rhu_int(n * MUSEUM_STORE_PCT), remaining)
    remaining -= museum
    outlet = min(rhu_int(n * FACTORY_OUTLET_PCT), remaining)
    remaining -= outlet
    ecommerce = min(rhu_int(n * ECOMMERCE_PCT), remaining)
    remaining -= ecommerce
    retail = remaining
    return {
        "museum_store_units": museum,
        "factory_outlet_units": outlet,
        "ecommerce_units": ecommerce,
        "retail_chain_units": retail,
    }


def cure_score(oil_type, actual_bake_temp_f, bake_duration_min):
    prof = CURE_PROFILES[oil_type]
    band_mid = (prof["min_temp"] + prof["max_temp"]) / 2
    band_half = (prof["max_temp"] - prof["min_temp"]) / 2
    temp = D(actual_bake_temp_f)
    if prof["min_temp"] <= temp <= prof["max_temp"]:
        temp_factor = Decimal("1") - abs(temp - band_mid) / band_half
    else:
        temp_factor = Decimal("0")
    duration_factor = min(D(bake_duration_min) / D(prof["min_minutes"]), Decimal("1.5")) / Decimal(
        "1.5"
    )
    return rhu_int(Decimal("60") * temp_factor + Decimal("40") * duration_factor)


def brand_floor_cents(import_landed_cost_cents):
    return rhu_int(D(import_landed_cost_cents) * BRAND_FLOOR_MULT)


def outlet_floor_cents(msrp_cents, channel):
    if channel == "FACTORY_OUTLET":
        return rhu_int(D(msrp_cents) * OUTLET_FLOOR_PCT)
    return int(msrp_cents)
