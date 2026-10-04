"""Calculation rules (SCAFFOLD section 1.3 / PRD section 3), implemented verbatim."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants
import store


def rhu(value, places):
    """Round-half-up a Decimal to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round-half-up a Decimal to integer cents."""
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# grade_determination: top-down bands, first match wins, all bounds inclusive
# ---------------------------------------------------------------------------

def determine_grade(flavor_brix, firmness_g, appearance_score, defect_pct):
    if flavor_brix >= Decimal("11.0") and firmness_g >= 350 and appearance_score >= 85 and defect_pct <= Decimal("3.0"):
        return "PREMIUM"
    if flavor_brix >= Decimal("9.0") and firmness_g >= 300 and appearance_score >= 70 and defect_pct <= Decimal("6.0"):
        return "STANDARD"
    if flavor_brix >= Decimal("7.0") and firmness_g >= 250 and appearance_score >= 50 and defect_pct <= Decimal("12.0"):
        return "PROCESS"
    if flavor_brix >= Decimal("5.0") and defect_pct <= Decimal("20.0"):
        return "JUICE"
    return "REJECT"


# ---------------------------------------------------------------------------
# cold_chain_evaluation
# ---------------------------------------------------------------------------

def evaluate_cold_chain(harvested_at, received_at, pulp_temp_c):
    delta = received_at - harvested_at
    seconds = Decimal(delta.days * 86400 + delta.seconds) + (
        Decimal(delta.microseconds) / Decimal(1000000)
    )
    precool_hours = rhu(seconds / Decimal(3600), 2)
    hard_reject = pulp_temp_c > constants.PULP_TEMP_HARD_REJECT_C
    compliant = (
        precool_hours <= constants.PRECOOL_MAX_HOURS
        and pulp_temp_c <= constants.PULP_TEMP_COMPLIANT_MAX_C
    )
    return precool_hours, hard_reject, compliant


# ---------------------------------------------------------------------------
# expected_yield_and_booking
# ---------------------------------------------------------------------------

def expected_first_harvest(berry_type, planted_on):
    return planted_on + timedelta(days=constants.DAYS_TO_FIRST_HARVEST[berry_type])


def expected_yield(berry_type, plants_planted_actual):
    return constants.YIELD_KG_PER_PLANT[berry_type] * Decimal(plants_planted_actual)


def find_eligible_window(variety_id, region_code, efh):
    """Half-open coverage [week_start, week_end); overlap rule gives at most one."""
    for w in store.db["harvest_windows"].values():
        if (
            w["variety_id"] == variety_id
            and w["region_code"] == region_code
            and w["week_start"] <= efh < w["week_end"]
        ):
            return w
    return None


# ---------------------------------------------------------------------------
# royalty_charge: tiered marginal royalty over the (variety, season_year) counter
# ---------------------------------------------------------------------------

def _tier_charge(start_pos, end_pos):
    """Charge for positions [start_pos, end_pos] (1-based, inclusive)."""
    total = 0
    t1_end = constants.TIER1_LIMIT
    t2_end = constants.TIER2_LIMIT
    lo = max(start_pos, 1)
    hi = min(end_pos, t1_end)
    if hi >= lo:
        total += (hi - lo + 1) * constants.TIER1_RATE
    lo = max(start_pos, t1_end + 1)
    hi = min(end_pos, t2_end)
    if hi >= lo:
        total += (hi - lo + 1) * constants.TIER2_RATE
    lo = max(start_pos, t2_end + 1)
    if end_pos >= lo:
        total += (end_pos - lo + 1) * constants.TIER3_RATE
    return total


def finalize_royalty(lot):
    """Compute royalty_final_cents / royalty_adjustment_cents for a lot reaching
    DEPLETED or RECALLED. Counter includes every lot of the same variety and
    season year, ordered by (shipped_at ASC, created_at ASC)."""
    siblings = [
        x for x in store.db["plant_lots"].values()
        if x["variety_id"] == lot["variety_id"] and x["season_year"] == lot["season_year"]
    ]
    siblings.sort(key=lambda x: (x["shipped_at"], x["created_at"]))
    c_before = 0
    for x in siblings:
        if x["id"] == lot["id"]:
            break
        c_before += x["quantity_plants"]
    final = _tier_charge(c_before + 1, c_before + lot["quantity_plants"])
    lot["royalty_final_cents"] = final
    lot["royalty_adjustment_cents"] = final - lot["royalty_provisional_cents"]


# ---------------------------------------------------------------------------
# pool_rate pipeline (pinned 8-step order) + per-lot gross
# ---------------------------------------------------------------------------

def pool_included_lots(pool):
    lots = []
    for lot in store.db["harvest_lots"].values():
        if lot["grade_status"] != "CERTIFIED" or lot["grade"] in (None, "REJECT"):
            continue
        if lot["received_at"] is None:
            continue
        if not (pool["week_start"] <= lot["received_at"] < pool["week_end"]):
            continue
        planting = store.db["plantings"][lot["planting_id"]]
        plant_lot = store.db["plant_lots"][planting["plant_lot_id"]]
        variety = store.db["varieties"][plant_lot["variety_id"]]
        if variety["berry_type"] != pool["berry_type"]:
            continue
        lots.append(lot)
    return lots


def run_pool_pipeline(pool, lots, price_cents_per_kg):
    """Steps (1)-(8) in the pinned order. Mutates pool's pipeline fields and
    returns the pool rate (Decimal, 4dp)."""
    total_net_kg = sum((l["net_kg"] for l in lots), Decimal(0))
    total_weighted_kg = sum(
        (l["net_kg"] * constants.GRADE_WEIGHT[l["grade"]] for l in lots), Decimal(0)
    )
    gross = rhu_int(total_net_kg * Decimal(price_cents_per_kg))
    fee = rhu_int(Decimal(gross) * constants.MARKETING_FEE_PCT)
    net = gross - fee
    if total_weighted_kg > 0:
        base_rate = rhu(Decimal(net) / total_weighted_kg, 4)
    else:
        base_rate = Decimal("0.0000")
    if pool["is_shoulder_week"]:
        pool_rate = rhu(base_rate * constants.SHOULDER_WEEK_MULTIPLIER, 4)
        distributable = rhu_int(Decimal(net) * constants.SHOULDER_WEEK_MULTIPLIER)
    else:
        pool_rate = base_rate
        distributable = net
    pool["total_net_kg"] = total_net_kg
    pool["total_weighted_kg"] = total_weighted_kg
    pool["gross_pool_revenue_cents"] = gross
    pool["marketing_fee_cents"] = fee
    pool["net_pool_revenue_cents"] = net
    pool["pool_distributable_cents"] = distributable
    return pool_rate


def lot_gross_cents(lot, pool_rate):
    """Per-lot round-half-up to integer cents FIRST, then summed downstream."""
    return rhu_int(lot["net_kg"] * constants.GRADE_WEIGHT[lot["grade"]] * pool_rate)
