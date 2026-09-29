"""Calculation rules (SCAFFOLD section 1.3 / PRD section 3).

Every constant below is quoted from the specification; none is invented.
"""

from decimal import Decimal

from common import D, ZERO, r2, r3

# --- vine geometry ---------------------------------------------------------
SQ_FT_PER_ACRE = Decimal("43560")

# --- labour ----------------------------------------------------------------
MIN_HOURLY_RATE = Decimal("16.50")
STD_SHIFT_HOURS = Decimal("8")
OVERTIME_MULTIPLIER = Decimal("1.5")
BURDEN_RATE = Decimal("0.2850")
MIN_CALL_IN_HOURS = Decimal("4")

# --- plan budget ----------------------------------------------------------
AT_RISK_FLOOR = Decimal("0.80")
EXHAUSTED_FLOOR = Decimal("1.00")

# --- irrigation ----------------------------------------------------------
AVAILABLE_WATER_FRACTION = Decimal("0.16")
REFILL_SHARE = Decimal("0.50")
MAX_SET_INCHES = Decimal("1.500")
DEFICIT_FACTOR = {
    "PREMIUM": Decimal("0.55"),
    "STANDARD": Decimal("0.75"),
    "BULK": Decimal("1.00"),
}

# --- yield ---------------------------------------------------------------
LB_PER_TON = Decimal("2000")
G_PER_LB = Decimal("453.592")
BERRY_GROWTH_RATE_PER_DAY = Decimal("0.004")

# --- pest ----------------------------------------------------------------
ACTION_THRESHOLD_PCT = {
    "POWDERY_MILDEW": Decimal("5.0"),
    "VINE_MEALYBUG": Decimal("2.0"),
    "BOTRYTIS": Decimal("3.0"),
    "LEAFHOPPER": Decimal("10.0"),
}

# --- harvest / window -----------------------------------------------------
HARVEST_TOLERANCE = Decimal("1.10")
NEARLY_FULL_FLOOR = Decimal("0.85")
FULL_FLOOR = Decimal("1.00")

# --- scheduling ----------------------------------------------------------
TRAVEL_BUFFER_MINUTES = 60

# --- settlement ----------------------------------------------------------
TIER_1_FLOOR = Decimal("15000")
TIER_2_FLOOR = Decimal("20000")
PROVISIONAL_PASS_THROUGH_SHARE = Decimal("0.50")

MAX_REVISION_ROUNDS = 2


# --------------------------------------------------------------------------
# block_vine_geometry
# --------------------------------------------------------------------------


def vine_geometry(vine_spacing_ft, row_spacing_ft, acres):
    """Both outputs truncate (floor), never round."""
    per_acre = int(SQ_FT_PER_ACRE / (D(vine_spacing_ft) * D(row_spacing_ft)))
    count = int(D(per_acre) * D(acres))
    return per_acre, count


# --------------------------------------------------------------------------
# work_order_labor_cost (variants 'estimated' and 'actual')
# --------------------------------------------------------------------------


def labor_cost(crew, vines, hours):
    vines = D(vines)
    hours = D(hours)
    if crew["pay_structure"] == "PIECE_RATE":
        structure_gross = vines * crew["piece_rate_per_vine"]
    else:
        regular = hours if hours < STD_SHIFT_HOURS else STD_SHIFT_HOURS
        overtime = hours - STD_SHIFT_HOURS
        if overtime < ZERO:
            overtime = ZERO
        structure_gross = (
            D(crew["crew_size"]) * crew["base_hourly_rate"]
            * (regular + overtime * OVERTIME_MULTIPLIER)
        )
    minimum_wage_floor = D(crew["crew_size"]) * MIN_HOURLY_RATE * hours
    gross_pay = r2(structure_gross if structure_gross > minimum_wage_floor else minimum_wage_floor)
    burden = r2(gross_pay * BURDEN_RATE)
    return r2(gross_pay + burden)


def cancellation_pay(crew):
    gross_pay = r2(D(crew["crew_size"]) * MIN_HOURLY_RATE * MIN_CALL_IN_HOURS)
    burden = r2(gross_pay * BURDEN_RATE)
    return r2(gross_pay + burden)


# --------------------------------------------------------------------------
# farming_plan_total_budget / budget_posture
# --------------------------------------------------------------------------


def plan_total_budget(plan, block):
    per_acre_total = (
        plan["pruning_budget_per_acre"]
        + plan["canopy_budget_per_acre"]
        + plan["irrigation_budget_per_acre"]
        + plan["pest_budget_per_acre"]
    )
    return r2(per_acre_total * block["acres"])


def budget_posture(total_budget, committed_cost):
    if total_budget == ZERO:
        return "EXHAUSTED" if committed_cost > ZERO else "WITHIN_BUDGET"
    # the ratio is NOT rounded before comparison; both comparisons are <=
    if committed_cost <= total_budget * AT_RISK_FLOOR:
        return "WITHIN_BUDGET"
    if committed_cost <= total_budget * EXHAUSTED_FLOOR:
        return "AT_RISK"
    return "EXHAUSTED"


# --------------------------------------------------------------------------
# irrigation_recommended_inches
# --------------------------------------------------------------------------


def irrigation_figures(payload, quality_target, seasonal_cap, season_applied):
    deficit_factor = DEFICIT_FACTOR[quality_target]
    et_demand = r3(payload["et0_inches"] * payload["crop_coefficient"])
    target = r3(et_demand * deficit_factor)
    shortfall_raw = (
        (payload["field_capacity_pct"] - payload["soil_moisture_pct"]) / Decimal("100")
        * payload["root_zone_depth_in"] * AVAILABLE_WATER_FRACTION
    )
    if shortfall_raw < ZERO:
        shortfall_raw = ZERO
    soil_shortfall = r3(shortfall_raw)
    refill = r3(soil_shortfall * REFILL_SHARE)
    gross = r3(target + refill - payload["effective_rain_inches"])
    if gross < ZERO:
        gross = Decimal("0.000")
    allowance = r3(D(seasonal_cap) - D(season_applied))
    if allowance < ZERO:
        allowance = Decimal("0.000")
    recommended = r3(min(gross, MAX_SET_INCHES, allowance))
    return {
        "deficit_factor": deficit_factor,
        "et_demand_inches": et_demand,
        "target_inches": target,
        "soil_shortfall_inches": soil_shortfall,
        "refill_inches": refill,
        "gross_requirement_inches": gross,
        "seasonal_allowance_inches": allowance,
        "recommended_inches": recommended,
    }


# --------------------------------------------------------------------------
# block_yield_estimate_tons
# --------------------------------------------------------------------------


def yield_estimate_tons(payload, vine_count_at_estimate, acres):
    total_clusters = D(vine_count_at_estimate) * payload["avg_clusters_per_vine"]
    if payload["method"] == "CLUSTER_COUNT":
        raw = total_clusters * payload["avg_cluster_weight_lb"] / LB_PER_TON
    else:
        cluster_weight_lb = (
            D(payload["berries_per_cluster"]) * payload["avg_berry_weight_g"] / G_PER_LB
        )
        growth_factor = Decimal("1") + BERRY_GROWTH_RATE_PER_DAY * D(payload["days_to_harvest"])
        raw = total_clusters * cluster_weight_lb * growth_factor / LB_PER_TON
    estimated_tons = r2(raw)
    if acres == ZERO:
        per_acre = Decimal("0.00")
    else:
        per_acre = r2(estimated_tons / acres)
    return estimated_tons, per_acre


# --------------------------------------------------------------------------
# harvest_load_net_tons
# --------------------------------------------------------------------------


def net_tons(gross_tons, tare_tons, mog_deduct_pct):
    return r2((gross_tons - tare_tons) * (Decimal("1") - mog_deduct_pct))


def window_posture(committed_tons, capacity_tons):
    if capacity_tons == ZERO:
        return "FULL"
    if committed_tons >= capacity_tons * FULL_FLOOR:
        return "FULL"
    if committed_tons >= capacity_tons * NEARLY_FULL_FLOOR:
        return "NEARLY_FULL"
    return "OPEN"


# --------------------------------------------------------------------------
# contract_period_settlement
# --------------------------------------------------------------------------


def volume_discount_pct(tier_basis):
    if tier_basis < TIER_1_FLOOR:
        return Decimal("0.00")
    if tier_basis < TIER_2_FLOOR:
        return Decimal("0.03")
    return Decimal("0.05")
