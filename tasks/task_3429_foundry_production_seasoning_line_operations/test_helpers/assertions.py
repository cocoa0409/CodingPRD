"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7, §3).

assert_{entity}(data) validates the response shape of one resource. The
expected_* calculators recompute PRD formulas with the pinned rounding so
tests can assert exact cents/scores without duplicating arithmetic.
"""
import math

import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .constants import (
    ALLOY_CENTS_PER_LB,
    BREACH_MULTIPLIER,
    BRAND_FLOOR_MULTIPLIER,
    CURE_PROFILES,
    CURE_SCORE_DURATION_WEIGHT,
    CURE_SCORE_TEMP_WEIGHT,
    DURATION_FACTOR_CAP,
    ECOMMERCE_PCT,
    ENERGY_RATE_CENTS_PER_KWH,
    FACTORY_OUTLET_FLOOR_PCT,
    FACTORY_OUTLET_PCT,
    LABOR_RATE_CENTS_PER_HOUR,
    MARGIN_MIN_PCT,
    MUSEUM_STORE_PCT,
    OVERHEAD_CENTS_PER_POURED_UNIT,
    PIG_IRON_CENTS_PER_LB,
    RETURNS_CENTS_PER_LB,
    SCRAP_RESTRICT_THRESHOLD,
    SCRAP_WATCH_THRESHOLD,
    SCRAP_STEEL_CENTS_PER_LB,
    SLAG_LOSS_PCT,
    STD_CONVERSION_CENTS_PER_UNIT,
    round_half_up,
    round_half_up_int,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def _assert_event_fields(data: dict):
    """PRD §2.5: append-only events carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ["SKILLET", "DUTCH_OVEN", "GRIDDLE", "GRILL_PAN", "BAKEWARE"]
    for f in ("target_weight_oz", "weight_tolerance_oz", "target_diameter_in",
              "diameter_tolerance_in", "min_wall_thickness_in"):
        assert isinstance(data[f], (int, float)) and data[f] > 0, f"{f} must be > 0"
    for f in ("wholesale_price_cents", "msrp_cents", "import_landed_cost_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert 1 <= data["peak_season_start_week"] <= 53
    assert 1 <= data["peak_season_end_week"] <= 53
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_production_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["planned_quantity"], int) and data["planned_quantity"] >= 1
    assert 1 <= data["scheduled_week"] <= 53
    assert data["state"] in ["PLANNED", "MOLDING", "POURING", "FINISHING",
                             "SEASONING", "COMPLETE", "CANCELLED"]
    assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["scrap_tier"] in ["GREEN", "WATCH", "RED"]
    for f in ("poured_units", "good_units", "scrapped_units", "defect_scrapped_units"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be an int >= 0"
    assert isinstance(data["scrap_weighted_units"], (int, float))
    assert isinstance(data["scrap_index"], (int, float))
    assert isinstance(data["unit_cost_provisional_cents"], int)
    assert isinstance(data["margin_flag"], bool)


def assert_melt_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str) and data["production_order_id"]
    assert data["furnace_id"] in ["FURNACE_A", "FURNACE_B"]
    assert data["state"] in ["CHARGING", "MELTING", "CHEMISTRY_CHECK", "ADJUSTMENT",
                             "CERTIFIED", "TAPPED", "EXHAUSTED", "HELD", "CANCELLED"]
    assert isinstance(data["planned_charge_cost_cents"], int)
    assert isinstance(data["actual_charge_cost_cents"], int)
    assert isinstance(data["adjustment_count"], int) and data["adjustment_count"] >= 0
    for f in ("pig_iron_lbs", "scrap_steel_lbs", "returns_lbs", "alloy_lbs",
              "poured_lbs", "returns_credit_lbs"):
        assert isinstance(data[f], (int, float)) and data[f] >= 0, f"{f} must be >= 0"


def assert_mold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str) and data["production_order_id"]
    assert data["state"] in ["PREPARED", "POURED", "SHAKEOUT_DONE",
                             "SAND_RECLAIMED", "CANCELLED"]
    assert isinstance(data["sand_weight_lbs"], (int, float)) and data["sand_weight_lbs"] > 0


def assert_casting_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str) and data["production_order_id"]
    assert isinstance(data["melt_batch_id"], str) and data["melt_batch_id"]
    assert isinstance(data["mold_id"], str) and data["mold_id"]
    assert data["state"] in ["POURED", "SHAKEOUT_DONE", "DEFECT_REVIEW", "REWORK",
                             "FINISHED", "SEASONING_QUEUED", "SEASONED", "SCRAPPED"]
    assert isinstance(data["pour_weight_oz"], (int, float)) and data["pour_weight_oz"] > 0
    assert isinstance(data["rework_count"], int) and 0 <= data["rework_count"] <= 2
    if data.get("scrap_reason") is not None:
        assert data["scrap_reason"] in ["DEFECT", "ORDER_CANCEL"]


def assert_defect_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["casting_unit_id"], str) and data["casting_unit_id"]
    assert data["defect_type"] in ["POROSITY", "COLD_SHUT", "MISRUN",
                                   "SAND_INCLUSION", "DIMENSIONAL", "CRACK"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["status"] in ["OPEN", "DISPOSITIONED"]
    if data.get("disposition") is not None:
        assert data["disposition"] in ["REWORK", "SCRAP", "USE_AS_IS"]


def assert_seasoning_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str) and data["production_order_id"]
    assert data["oil_type"] in ["SOYBEAN", "CANOLA", "FLAXSEED"]
    assert 1 <= data["coating_count"] <= 3
    assert isinstance(data["unit_ids"], list)
    assert data["unit_count"] == len(data["unit_ids"])
    assert data["oven_id"] == "OVEN_1"
    assert data["state"] in ["COATING", "BAKING", "RELEASED", "FAILED"]
    if data.get("cure_score") is not None:
        assert isinstance(data["cure_score"], int) and 0 <= data["cure_score"] <= 100


def assert_environmental_permit(data: dict):
    _assert_common_fields(data)
    assert data["permit_type"] in ["AIR_EMISSIONS", "SAND_RECLAMATION", "DUST_CONTROL"]
    assert isinstance(data["limit_value"], (int, float)) and data["limit_value"] > 0
    assert isinstance(data["measurement_unit"], str) and data["measurement_unit"]
    assert data["compliance_period"] == "MONTHLY"
    assert data["status"] in ["ACTIVE", "WARNING", "BREACH", "REMEDIATION"]
    assert isinstance(data["over_limit_reading_count_current_period"], int)
    assert data["over_limit_reading_count_current_period"] >= 0


def assert_emissions_reading(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["permit_id"], str) and data["permit_id"]
    assert isinstance(data["reading_value"], (int, float)) and data["reading_value"] > 0
    assert data["source"] in ["MELT_FURNACE", "SHAKEOUT_LINE", "SAND_PLANT",
                              "SEASONING_OVEN"]
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_inventory_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str) and data["product_id"]
    for f in ("on_hand_units", "reserved_units", "shipped_units",
              "outlet_sold_units", "available_units"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"], (
        f"available_units {data['available_units']} != on_hand {data['on_hand_units']} "
        f"- reserved {data['reserved_units']}")


def assert_retail_allocation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["inventory_record_id"], str) and data["inventory_record_id"]
    assert data["channel"] in ["RETAIL_CHAIN", "ECOMMERCE", "FACTORY_OUTLET",
                               "MUSEUM_STORE"]
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 1
    assert isinstance(data["ship_week"], str) and data["ship_week"]
    assert data["status"] in ["PROPOSED", "CONFIRMED", "SHIPPED", "CANCELLED"]


def assert_outlet_sale(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert data["channel"] in ["FACTORY_OUTLET", "MUSEUM_STORE"]
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["floor_price_cents"], int)
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


# --- Domain invariant checkers --------------------------------------------------

def assert_iron_mass_conserved(melt: dict):
    """PRD §3.3: tapped_lbs == poured_lbs + slag_loss_lbs + remaining_iron_lbs
    at every observable instant after tap."""
    if melt.get("tapped_lbs") is None:
        return
    total = melt["poured_lbs"] + melt["slag_loss_lbs"] + melt["remaining_iron_lbs"]
    assert total == pytest.approx(melt["tapped_lbs"], abs=0.005), (
        f"iron ledger broken: poured {melt['poured_lbs']} + slag "
        f"{melt['slag_loss_lbs']} + remaining {melt['remaining_iron_lbs']} "
        f"!= tapped {melt['tapped_lbs']}")


def assert_inventory_conservation(record: dict):
    """PRD §3.8: available_units == on_hand_units - reserved_units."""
    assert record["available_units"] == record["on_hand_units"] - record["reserved_units"]


def assert_scrap_tier_matches(order: dict):
    """PRD §2.8: tier derived from scrap_index with inclusive lower bounds."""
    idx = order["scrap_index"]
    if idx >= SCRAP_RESTRICT_THRESHOLD:
        expected = "RED"
    elif idx >= SCRAP_WATCH_THRESHOLD:
        expected = "WATCH"
    else:
        expected = "GREEN"
    assert order["scrap_tier"] == expected, (
        f"scrap_tier {order['scrap_tier']} != expected {expected} "
        f"for scrap_index {idx}")


# --- Expected-value calculators (PRD formulas, pinned rounding) -----------------

def expected_carbon_equivalent(carbon_pct, silicon_pct, phosphorus_pct) -> float:
    """PRD §3.3: carbon + (silicon + phosphorus)/3, 2dp round_half_up."""
    return round_half_up(carbon_pct + (silicon_pct + phosphorus_pct) / 3.0, 2)


def expected_planned_charge_cost_cents(planned_iron_lbs, pig_pct, scrap_pct,
                                       returns_pct, alloy_pct) -> int:
    """PRD §3.3: ONE rounding over the whole weighted mix."""
    weighted = (pig_pct * PIG_IRON_CENTS_PER_LB
                + scrap_pct * SCRAP_STEEL_CENTS_PER_LB
                + returns_pct * RETURNS_CENTS_PER_LB
                + alloy_pct * ALLOY_CENTS_PER_LB)
    return round_half_up_int(planned_iron_lbs * weighted / 100)


def expected_charge_lines_cents(pig_iron_lbs, scrap_steel_lbs, returns_lbs,
                                alloy_lbs) -> int:
    """PRD §3.3 actual variant: each line rounded half-up first, then summed."""
    return (round_half_up_int(pig_iron_lbs * PIG_IRON_CENTS_PER_LB)
            + round_half_up_int(scrap_steel_lbs * SCRAP_STEEL_CENTS_PER_LB)
            + round_half_up_int(returns_lbs * RETURNS_CENTS_PER_LB)
            + round_half_up_int(alloy_lbs * ALLOY_CENTS_PER_LB))


def expected_slag_loss_lbs(tapped_lbs) -> float:
    """PRD §3.3: round_half_up(tapped_lbs * 0.03, 2)."""
    return round_half_up(tapped_lbs * SLAG_LOSS_PCT, 2)


def expected_returns_credit_lbs(pour_weight_oz) -> float:
    """PRD §3.3: round_half_up(pour_weight_oz / 16.0, 2)."""
    return round_half_up(pour_weight_oz / 16.0, 2)


def expected_pour_total_lbs(unit_count, pour_weight_per_unit_oz) -> float:
    return unit_count * pour_weight_per_unit_oz / 16.0


def expected_scrap_index(scrap_weighted_units, poured_units) -> float:
    """PRD §2.8: 0 when nothing poured, else 4dp round_half_up."""
    if poured_units == 0:
        return 0
    return round_half_up(scrap_weighted_units / poured_units, 4)


def expected_unit_cost_provisional_cents(material_to_date_cents,
                                         planned_quantity) -> int:
    """PRD §3.2: round_half_up(material / planned_quantity) + 1450."""
    return (round_half_up_int(material_to_date_cents / planned_quantity)
            + STD_CONVERSION_CENTS_PER_UNIT)


def expected_unit_cost_final_cents(material_cents, labor_hours, energy_kwh,
                                   poured_units, good_units) -> int:
    """PRD §3.2 final variant: labor and energy rounded per line, overhead per
    poured unit, then the total divided by good units, round_half_up."""
    labor = round_half_up_int(labor_hours * LABOR_RATE_CENTS_PER_HOUR)
    energy = round_half_up_int(energy_kwh * ENERGY_RATE_CENTS_PER_KWH)
    overhead = OVERHEAD_CENTS_PER_POURED_UNIT * poured_units
    return round_half_up_int((material_cents + labor + energy + overhead) / good_units)


def expected_margin_flag(wholesale_price_cents, unit_cost_final_cents) -> bool:
    """PRD §3.2: true when (wholesale - final) / wholesale < 0.30."""
    return ((wholesale_price_cents - unit_cost_final_cents) / wholesale_price_cents
            < MARGIN_MIN_PCT)


def expected_min_good_units(planned_quantity) -> int:
    """PRD §3.2: completion yield gate, ceil(0.85 * planned_quantity)."""
    return math.ceil(0.85 * planned_quantity)


def expected_cure_score(oil_type, actual_bake_temp_f, bake_duration_min) -> int:
    """PRD §3.6: round_half_up(60 * temp_factor + 40 * duration_factor)."""
    profile = CURE_PROFILES[oil_type]
    lo, hi, mins = profile["min_temp_f"], profile["max_temp_f"], profile["min_minutes"]
    band_mid = (lo + hi) / 2
    band_half = (hi - lo) / 2
    if lo <= actual_bake_temp_f <= hi:
        temp_factor = 1 - abs(actual_bake_temp_f - band_mid) / band_half
    else:
        temp_factor = 0
    duration_factor = min(bake_duration_min / mins, DURATION_FACTOR_CAP) / DURATION_FACTOR_CAP
    return round_half_up_int(CURE_SCORE_TEMP_WEIGHT * temp_factor
                             + CURE_SCORE_DURATION_WEIGHT * duration_factor)


def expected_channel_split(build_qty) -> dict:
    """PRD §3.8 waterfall: museum, outlet, ecommerce each round_half_up and
    clamped by the remaining pool; retail chain absorbs the rest."""
    remaining = build_qty
    museum = min(round_half_up_int(build_qty * MUSEUM_STORE_PCT), remaining)
    remaining -= museum
    outlet = min(round_half_up_int(build_qty * FACTORY_OUTLET_PCT), remaining)
    remaining -= outlet
    ecommerce = min(round_half_up_int(build_qty * ECOMMERCE_PCT), remaining)
    remaining -= ecommerce
    return {
        "museum_store_units": museum,
        "factory_outlet_units": outlet,
        "ecommerce_units": ecommerce,
        "retail_chain_units": remaining,
    }


def expected_brand_floor_cents(import_landed_cost_cents) -> int:
    """PRD §3.1: round_half_up(import_landed_cost_cents * 1.15)."""
    return round_half_up_int(import_landed_cost_cents * BRAND_FLOOR_MULTIPLIER)


def expected_outlet_floor_cents(msrp_cents, channel) -> int:
    """PRD §3.8: FACTORY_OUTLET floor is round_half_up(msrp * 0.55);
    MUSEUM_STORE floor is the full msrp."""
    if channel == "FACTORY_OUTLET":
        return round_half_up_int(msrp_cents * FACTORY_OUTLET_FLOOR_PCT)
    return msrp_cents


def expected_sand_rate(reclaimed_lbs_list, sand_weight_lbs_list) -> float:
    """PRD §3.4: month-to-date sums ratio, 4dp round_half_up."""
    return round_half_up(sum(reclaimed_lbs_list) / sum(sand_weight_lbs_list), 4)


def expected_immediate_breach_value(limit_value) -> float:
    """PRD §3.7: a single reading >= 1.5 * limit breaches immediately."""
    return limit_value * BREACH_MULTIPLIER
