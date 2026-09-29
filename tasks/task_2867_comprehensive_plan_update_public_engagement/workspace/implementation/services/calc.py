"""The twelve calculations of PRD 2.6 / 3.2 / 3.3 / 3.6 / 3.7 / 3.9.

Every arithmetic step below runs on Decimal; rounding is always round half up
and always happens exactly where the PRD says it happens.
"""
from decimal import Decimal

import constants as K
from db import d1, d2, dec, rhu_int


# --- 1. land_capacity_units (PRD 3.2) ---------------------------------------

def capacity_variant_for(method):
    return "GROSS_CAPACITY" if method == "TREND" else "NET_CAPACITY"


def land_capacity_units(inv, method):
    vacant = dec(inv["vacant_acres"])
    under = dec(inv["underutilized_acres"])
    constrained = dec(inv["infrastructure_constrained_acres"])
    density = dec(inv["allowed_density_units_per_acre"])
    if method == "TREND":
        # GROSS_CAPACITY: one product, rounded once at the end.
        return rhu_int((vacant + under) * density)
    # NET_CAPACITY: three discounts, rounded once at the very end.
    acres = (vacant - constrained) + under * K.UNDERUTILIZED_REALIZATION_FACTOR
    return rhu_int(acres * density * K.MARKET_FACTOR)


# --- 2. projected_demand_units (PRD 3.2) ------------------------------------

def projected_demand_units(scenario, base_year):
    horizon_years = int(scenario["horizon_year"]) - int(base_year)
    base_hh = dec(scenario["base_households"])
    rate = dec(scenario["annual_household_growth_rate"])
    household_growth = base_hh * ((Decimal(1) + rate) ** horizon_years) - base_hh
    job_driven = dec(scenario["job_growth_total"]) / K.JOBS_PER_HOUSEHOLD
    if scenario["method"] == "TREND":
        driver = household_growth
    else:
        driver = household_growth if household_growth >= job_driven else job_driven
    total = (driver + dec(scenario["demolition_replacement_units"]))
    return rhu_int(total * (Decimal(1) + K.VACANCY_ALLOWANCE))


def capacity_gap_units(demand, capacity):
    gap = int(demand) - int(capacity)
    return gap if gap > 0 else 0


# --- 3. housing_allocation_waterfall (PRD 3.3) ------------------------------

def run_waterfall(pool, rows_by_tier):
    """Return {tier: {tier_capacity_units, carryover_in_units,
    accommodated_units, shortfall_units}} plus the shortfall total.

    `pool` is the adopted scenario's land_capacity_units, or 0 when the plan
    has no adopted scenario. Tiers are visited in the fixed statutory order.
    """
    pool = dec(pool)
    carryover = 0
    results = {}
    shortfall_total = 0
    for tier in K.TIER_ORDER:
        row = rows_by_tier.get(tier)
        if row is None:
            # No row: contributes nothing and passes the carryover downstream.
            continue
        tier_capacity = rhu_int(pool * K.TIER_SUITABILITY_SHARE[tier])
        carryover_in = carryover
        available = tier_capacity + carryover_in
        assigned = int(row["assigned_units"])
        accommodated = assigned if assigned < available else available
        shortfall = assigned - accommodated
        carryover = available - accommodated
        results[tier] = {
            "tier_capacity_units": tier_capacity,
            "carryover_in_units": carryover_in,
            "accommodated_units": accommodated,
            "shortfall_units": shortfall,
        }
        shortfall_total += shortfall
    return results, shortfall_total


# --- 4. participation_record_weight (PRD 3.6) -------------------------------

def is_underrepresented(demographic_group):
    return demographic_group in K.UNDERREPRESENTED_GROUPS


def record_weight(weighting_variant, interpreter_used):
    if weighting_variant == "OUTREACH_WEIGHTED" and interpreter_used:
        return K.OUTREACH_INTERPRETER_WEIGHT
    return K.BASE_WEIGHT


# --- 5 & 6. equity shares (PRD 3.6) -----------------------------------------

def equity_share(underrepresented_total, weighted_total):
    """100 * under / total to one decimal place; 0.0 when the denominator is 0."""
    total = dec(weighted_total)
    if total == 0:
        return Decimal("0.0")
    return d1(Decimal(100) * dec(underrepresented_total) / total)


def weight_sum(values):
    total = Decimal(0)
    for value in values:
        total += dec(value)
    return d1(total)


# --- 7. alternative_net_impact_score (PRD 3.7) ------------------------------

def score_alternative(traffic, ghg, habitat, water):
    raw = d2(K.IMPACT_WEIGHT_TRAFFIC * dec(traffic)
             + K.IMPACT_WEIGHT_GHG * dec(ghg)
             + K.IMPACT_WEIGHT_HABITAT * dec(habitat)
             + K.IMPACT_WEIGHT_WATER * dec(water))
    # The tier is keyed on the RAW score, never on the net score.
    if raw >= K.HIGH_IMPACT_THRESHOLD:
        credit = d2(raw * K.HIGH_CREDIT_RATE)
    elif raw >= K.MID_IMPACT_THRESHOLD:
        credit = d2(raw * K.MID_CREDIT_RATE)
    else:
        credit = Decimal("0.00")
    net = d2(raw - credit)
    return raw, credit, net


# --- 8. preferred_alternative_selector (PRD 3.7) ----------------------------

def rank_alternatives(candidates):
    """net_impact_score ASC, raw_impact_score ASC, created_at ASC."""
    return sorted(candidates,
                  key=lambda a: (dec(a["net_impact_score"]),
                                 dec(a["raw_impact_score"]),
                                 a["created_at"], a["_seq"]))


# --- 9. compliance_posture (PRD 2.9) ----------------------------------------

def compliance_posture(plan):
    if plan["state_review_status"] == "DEFICIENT":
        return "FROZEN"
    if int(plan["open_consistency_link_count"]) > 0:
        return "CONSISTENCY_HOLD"
    if plan["adopted_scenario_id"] is None or int(plan["housing_shortfall_total"]) > 0:
        return "CAPACITY_HOLD"
    if dec(plan["equity_share_pct"]) < K.EQUITY_MIN_SHARE_PCT:
        return "EQUITY_HOLD"
    return "CLEAR"


# --- 10. indicator_on_track (PRD 3.9) ---------------------------------------

def indicator_on_track(direction, latest_value, target_value):
    if latest_value is None:
        return False
    latest = dec(latest_value)
    target = dec(target_value)
    if direction == "INCREASE":
        return latest >= target
    return latest <= target
