"""Every derived number in the surface (PRD 2.6, 3.1-3.9).

Money is integer cents, units are integers, derived percentages carry exactly
two decimal places. All arithmetic goes through decimal.Decimal; float never
participates in a rounding decision.
"""
from decimal import Decimal

from store import ordered, store
from util import (D, ceil_int, dsqrt, floor_int, month_offset, rhu2,
                  rhu_int, round_half_up)

# ---- pinned constants ----------------------------------------------------
INTERMITTENT_CV_THRESHOLD = D("0.75")
MAX_SWING_PCT = D(25)
Z_TIERS = ((D("99.0"), D("2.33")), (D("97.5"), D("1.96")),
           (D("95.0"), D("1.65")), (D("90.0"), D("1.28")))
Z_FLOOR = D("0.84")
DAYS_PER_MONTH = D(30)
HOURS_ROUNDING_DP = 6
PROTECTED_RANK = 2
CAPACITY_HOURLY_COST_CENTS = D(25000)
TRADE_TIER_1_CENTS = D(1000000)
TRADE_TIER_2_CENTS = D(5000000)
BIAS_THRESHOLD_PCT = D("5.00")
GRADE_A_MAX_WMAPE = D("10.00")
GRADE_B_MAX_WMAPE = D("20.00")
GRADE_C_MAX_WMAPE = D("35.00")
MAX_REOPENS = 2
MAX_REVISION_ROUNDS = 3
CHANGEOVER_BUFFER_DAYS = 2
AT_RISK_CONSTRAINED_PLAN_MIN = 1


# ==========================================================================
# calc_inventory_policy
# ==========================================================================
def z_factor(service_level_target_pct):
    slt = D(service_level_target_pct)
    for threshold, z in Z_TIERS:
        if slt >= threshold:
            return z
    return Z_FLOOR


def calc_inventory_policy(item):
    z = z_factor(item["service_level_target_pct"])
    cv = D(item["demand_cv"])
    amd = D(item["avg_monthly_demand_units"])
    ltd = D(item["lead_time_days"])
    # one ceiling, applied once at the very end of the expression
    item["safety_stock_units"] = ceil_int(z * cv * amd * dsqrt(ltd / DAYS_PER_MONTH))
    # pinned order: the cycle-stock term is ceilinged FIRST, then the
    # already-ceilinged safety stock is added
    item["reorder_point_units"] = (ceil_int(amd * ltd / DAYS_PER_MONTH)
                                  + item["safety_stock_units"])


# ==========================================================================
# calc_statistical_baseline
# ==========================================================================
def select_method(item):
    if item["lifecycle_state"] == "PRELAUNCH":
        return "ANALOG_PROFILE"
    if D(item["demand_cv"]) >= INTERMITTENT_CV_THRESHOLD:
        return "CROSTON_FLAT"
    return "HOLT_WINTERS"


def calc_statistical_baseline(cycle, item, month, level_units,
                              trend_units_per_month, seasonal_index,
                              causal_uplift_pct):
    method = select_method(item)
    offset = month_offset(month, cycle["horizon_start_month"])
    level = D(level_units)
    trend = D(trend_units_per_month)
    seasonal = D(seasonal_index)
    if method == "HOLT_WINTERS":
        raw = (level + trend * D(offset)) * seasonal
    elif method == "CROSTON_FLAT":
        raw = level
    else:  # ANALOG_PROFILE -- trend suppressed, ramp factor applied
        raw = level * (D(item["npi_ramp_pct"]) / D(100)) * seasonal
    baseline_units = rhu_int(raw * (D(1) + D(causal_uplift_pct) / D(100)))
    return method, baseline_units


# ==========================================================================
# calc_consensus_units
# ==========================================================================
def calc_applied_delta(adjustment_type, delta_units, forecast, item, promotion):
    if adjustment_type == "PROMOTION":
        base = D(forecast["baseline_units"])
        lift_term = rhu_int(base * D(promotion["lift_pct"]) / D(100))
        cannib_term = rhu_int(base * D(promotion["cannibalization_pct"]) / D(100))
        return lift_term - cannib_term
    if adjustment_type == "SALES_INTELLIGENCE":
        return int(delta_units)
    return rhu_int(D(delta_units) * D(item["npi_ramp_pct"]) / D(100))


def swing_ceiling(baseline_units):
    return rhu_int(D(baseline_units) * MAX_SWING_PCT / D(100))


def adjustments_of(forecast_id):
    return [a for a in store.adjustments.values()
            if a["demand_forecast_id"] == forecast_id]


def rollup_consensus(forecast):
    """Recompute consensus_units and endorsed_adjustment_count in place."""
    contributing = [a for a in adjustments_of(forecast["id"])
                    if a["status"] in ("ENDORSED", "COMMITTED")]
    forecast["endorsed_adjustment_count"] = len(contributing)
    if forecast["status"] == "RUNOUT_TRUNCATED":
        forecast["consensus_units"] = 0
        return
    forecast["consensus_units"] = (forecast["baseline_units"]
                                  + sum(a["applied_delta_units"] for a in contributing))


# ==========================================================================
# calc_constrained_supply
# ==========================================================================
def hours_to_units(hours, units_per_hour):
    product = D(hours) * D(units_per_hour)
    return floor_int(round_half_up(product, HOURS_ROUNDING_DP))


def horizon_window(cycle):
    """Half-open [first day of horizon_start_month, first day after horizon_end_month)."""
    from util import add_months, first_day
    return (first_day(cycle["horizon_start_month"]),
            first_day(add_months(cycle["horizon_end_month"], 1)))


def forecasts_of(cycle_id, item_id):
    return [f for f in store.forecasts.values()
            if f["cycle_id"] == cycle_id and f["item_id"] == item_id]


def calc_constrained_supply(cycle, item, family):
    locked = [f for f in forecasts_of(cycle["id"], item["id"])
              if f["status"] == "CONSENSUS_LOCKED"]
    gross_requirement_units = sum(f["consensus_units"] for f in locked)
    target_build_units = item["safety_stock_units"]
    material_cap_units = item["material_supply_cap_units"]

    window_start, window_end = horizon_window(cycle)
    eligible = [b for b in store.capacity_blocks.values()
                if b["family_id"] == item["family_id"]
                and b["start_date"] >= window_start
                and b["end_date"] <= window_end]
    eligible_hours = sum((D(b["available_hours"]) for b in eligible), D(0))
    available_units = hours_to_units(eligible_hours, family["units_per_hour"])

    on_hand = item["on_hand_units"]
    if cycle["supply_review_policy"] == "NET_INVENTORY_FIRST":
        demand_side_units = max(0, gross_requirement_units + target_build_units - on_hand)
        constrained_units = min(demand_side_units, available_units, material_cap_units)
    else:  # GROSS_CAPACITY_FIRST
        demand_side_units = gross_requirement_units + target_build_units
        capped = min(demand_side_units, available_units, material_cap_units)
        constrained_units = max(0, capped - on_hand)

    shortfall_units = max(0, demand_side_units - constrained_units)

    if material_cap_units <= available_units and material_cap_units < demand_side_units:
        constraint_type = "MATERIAL"
    elif available_units < demand_side_units:
        constraint_type = "CAPACITY"
    elif constrained_units < gross_requirement_units:
        constraint_type = "INVENTORY_TARGET"
    else:
        constraint_type = "NONE"

    return {
        "gross_requirement_units": gross_requirement_units,
        "target_build_units": target_build_units,
        "available_units": available_units,
        "material_cap_units": material_cap_units,
        "demand_side_units": demand_side_units,
        "constrained_units": constrained_units,
        "shortfall_units": shortfall_units,
        "constraint_type": constraint_type,
        "unallocated_units": constrained_units,
    }


# ==========================================================================
# calc_rationing_waterfall
# ==========================================================================
def fill_rate(allocated_units, requested_units):
    if requested_units == 0:
        return rhu2(D("100.00"))
    return rhu2(D(allocated_units) / D(requested_units) * D(100))


def calc_rationing_waterfall(plan):
    """Returns [(customer, requested, allocated, status, pass)] plus the leftover."""
    locked = [f for f in forecasts_of(plan["cycle_id"], plan["item_id"])
              if f["status"] == "CONSENSUS_LOCKED"]
    requested = {}
    for f in locked:
        requested[f["customer_id"]] = requested.get(f["customer_id"], 0) + f["consensus_units"]

    candidates = [store.customers[cid] for cid in requested if cid in store.customers]
    candidates = ordered(candidates)

    allocated = {}
    status = {}
    pass_name = {}
    remaining = plan["constrained_units"]

    for c in candidates:
        if c["credit_hold"]:
            allocated[c["id"]] = 0
            status[c["id"]] = "WITHHELD_CREDIT_HOLD"
            pass_name[c["id"]] = "NONE"
        elif requested[c["id"]] == 0:
            allocated[c["id"]] = 0
            status[c["id"]] = "ALLOCATED"
            pass_name[c["id"]] = "NONE"

    protected = [c for c in candidates
                 if not c["credit_hold"] and requested[c["id"]] > 0
                 and c["priority_rank"] <= PROTECTED_RANK]
    protected.sort(key=lambda c: (c["priority_rank"], c["created_at"], c["_seq"]))
    for c in protected:
        grant = min(requested[c["id"]], remaining)
        allocated[c["id"]] = grant
        status[c["id"]] = "ALLOCATED"
        pass_name[c["id"]] = "PROTECTED"
        remaining -= grant

    pool = [c for c in candidates
            if not c["credit_hold"] and requested[c["id"]] > 0
            and c["priority_rank"] > PROTECTED_RANK]
    total = sum(requested[c["id"]] for c in pool)
    if total == 0 or remaining == 0:
        for c in pool:
            allocated[c["id"]] = 0
            status[c["id"]] = "ALLOCATED"
            pass_name[c["id"]] = "NONE"
    else:
        start = min(remaining, total)
        shares = {}
        for c in pool:
            share = D(start) * D(requested[c["id"]]) / D(total)
            shares[c["id"]] = share
            allocated[c["id"]] = floor_int(share)
            status[c["id"]] = "ALLOCATED"
            pass_name[c["id"]] = "PRO_RATA"
        top_up = start - sum(allocated[c["id"]] for c in pool)
        if top_up > 0:
            ranked = sorted(
                pool,
                key=lambda c: (-(shares[c["id"]] - D(allocated[c["id"]])),
                               c["priority_rank"], c["created_at"], c["_seq"]),
            )
            for c in ranked[:top_up]:
                allocated[c["id"]] += 1
        remaining = remaining - start

    rows = []
    for c in candidates:
        rows.append((c, requested[c["id"]], allocated[c["id"]],
                     status[c["id"]], pass_name[c["id"]]))
    return rows, remaining


# ==========================================================================
# calc_scenario_gap_closure -- seven pinned steps, no iteration
# ==========================================================================
def plans_of(cycle_id, item_id=None):
    rows = [p for p in store.supply_plans.values() if p["cycle_id"] == cycle_id]
    if item_id is not None:
        rows = [p for p in rows if p["item_id"] == item_id]
    return rows


def active_plan_for(cycle_id, item_id):
    for p in ordered(plans_of(cycle_id, item_id)):
        if p["status"] in ("PLANNED", "RATIONED"):
            return p
    return None


def calc_scenario_gap_closure(scenario, cycle):
    if scenario["scenario_type"] == "CAPACITY_INVESTMENT":
        plan = active_plan_for(cycle["id"], scenario["target_item_id"])
        item = store.items[scenario["target_item_id"]]
        family = store.families[item["family_id"]]
        # step 1
        capacity_units = hours_to_units(scenario["added_capacity_hours"],
                                        family["units_per_hour"])
        incremental_units = min(capacity_units, plan["shortfall_units"])
        # step 2
        gross_uplift_cents = incremental_units * item["unit_price_cents"]
        # step 3
        investment_cost_cents = rhu_int(D(scenario["added_capacity_hours"])
                                        * CAPACITY_HOURLY_COST_CENTS)
    else:  # PRICE_REALIZATION
        incremental_units = 0
        gross_uplift_cents = rhu_int(D(cycle["plan_value_cents"])
                                     * D(scenario["price_increase_pct"]) / D(100))
        investment_cost_cents = 0

    # step 4
    pre_trade_closure_cents = gross_uplift_cents - investment_cost_cents
    # step 5 -- the tier reads pre_trade_closure_cents and nothing else
    pre = D(pre_trade_closure_cents)
    if pre >= TRADE_TIER_2_CENTS:
        trade_rate_pct = D("8.0")
    elif pre >= TRADE_TIER_1_CENTS:
        trade_rate_pct = D("6.0")
    else:
        trade_rate_pct = D("4.0")
    # step 6 -- the rate applies to GROSS uplift
    trade_spend_cents = rhu_int(D(gross_uplift_cents) * trade_rate_pct / D(100))
    # step 7
    net_gap_closure_cents = pre_trade_closure_cents - trade_spend_cents

    scenario["incremental_units"] = incremental_units
    scenario["gross_uplift_cents"] = gross_uplift_cents
    scenario["investment_cost_cents"] = investment_cost_cents
    scenario["pre_trade_closure_cents"] = pre_trade_closure_cents
    scenario["trade_rate_pct"] = float(trade_rate_pct)
    scenario["trade_spend_cents"] = trade_spend_cents
    scenario["net_gap_closure_cents"] = net_gap_closure_cents


# ==========================================================================
# calc_cycle_financials + calc_cycle_posture
# ==========================================================================
def scenarios_of(cycle_id):
    return [s for s in store.scenarios.values() if s["cycle_id"] == cycle_id]


def calc_cycle_financials(cycle):
    plan_value_cents = 0
    constrained_plan_count = 0
    for p in plans_of(cycle["id"]):
        if p["status"] in ("PLANNED", "RATIONED", "COMMITTED"):
            item = store.items[p["item_id"]]
            plan_value_cents += p["constrained_units"] * item["unit_price_cents"]
        if p["status"] in ("PLANNED", "RATIONED") and p["constraint_type"] != "NONE":
            constrained_plan_count += 1
    gross_gap_cents = cycle["financial_commitment_cents"] - plan_value_cents
    selected_closure_cents = sum(
        s["net_gap_closure_cents"] for s in scenarios_of(cycle["id"])
        if s["status"] in ("SELECTED", "EXECUTED"))
    cycle["plan_value_cents"] = plan_value_cents
    cycle["gross_gap_cents"] = gross_gap_cents
    cycle["selected_closure_cents"] = selected_closure_cents
    cycle["residual_gap_cents"] = gross_gap_cents - selected_closure_cents
    cycle["constrained_plan_count"] = constrained_plan_count


def calc_cycle_posture(cycle):
    if cycle["status"] == "PUBLISHED":
        cycle["posture"] = "FROZEN"
    elif (cycle["residual_gap_cents"] > 0
          or cycle["constrained_plan_count"] >= AT_RISK_CONSTRAINED_PLAN_MIN):
        cycle["posture"] = "AT_RISK"
    else:
        cycle["posture"] = "GREEN"


# ==========================================================================
# calc_accuracy_record
# ==========================================================================
def calc_accuracy_record(cycle, item, customer, actual_units):
    snapshot = sum(f["consensus_units"] for f in store.forecasts.values()
                   if f["cycle_id"] == cycle["id"] and f["item_id"] == item["id"]
                   and f["customer_id"] == customer["id"]
                   and f["status"] == "CONSENSUS_LOCKED")
    signed = snapshot - actual_units
    abs_error = abs(signed)
    if actual_units == 0:
        ape = None
        ape_dec = None
    else:
        ape_dec = round_half_up(D(abs_error) / D(actual_units) * D(100), 2)
        ape = float(ape_dec)
    family = store.families[item["family_id"]]
    return {
        "forecast_units_snapshot": snapshot,
        "signed_error_units": signed,
        "abs_error_units": abs_error,
        "ape_pct": ape,
        "_ape_dec": ape_dec,
        "accountable_planner_user_id": family["accountable_planner_user_id"],
    }


# ==========================================================================
# calc_accuracy_rollup -- MAPE round-then-average, WMAPE aggregate-then-round
# ==========================================================================
def calc_accuracy_rollup(records):
    out = {
        "record_count": len(records),
        "mape_pct": None,
        "wmape_pct": None,
        "bias_pct": None,
        "bias_flag": "NONE",
        "accuracy_grade": "UNGRADED",
        "total_actual_units": 0,
        "total_abs_error_units": 0,
        "worst_item_id": None,
    }
    if not records:
        return out

    total_actual = sum(r["actual_units"] for r in records)
    total_abs = sum(r["abs_error_units"] for r in records)
    total_signed = sum(r["signed_error_units"] for r in records)
    out["total_actual_units"] = total_actual
    out["total_abs_error_units"] = total_abs

    # variant A: unweighted MAPE over the already-rounded per-record ape_pct
    scored = [r for r in records if r.get("_ape_dec") is not None]
    if scored:
        mean = sum((r["_ape_dec"] for r in scored), D(0)) / D(len(scored))
        out["mape_pct"] = float(rhu2(mean))

    # variant B: volume-weighted WMAPE over the FULL record set
    wmape_dec = None
    if total_actual != 0:
        wmape_dec = round_half_up(D(total_abs) / D(total_actual) * D(100), 2)
        out["wmape_pct"] = float(wmape_dec)
        bias_dec = round_half_up(D(total_signed) / D(total_actual) * D(100), 2)
        out["bias_pct"] = float(bias_dec)
        if bias_dec >= BIAS_THRESHOLD_PCT:
            out["bias_flag"] = "OVER_FORECAST"
        elif bias_dec <= -BIAS_THRESHOLD_PCT:
            out["bias_flag"] = "UNDER_FORECAST"

    if wmape_dec is None:
        out["accuracy_grade"] = "UNGRADED"
    elif wmape_dec <= GRADE_A_MAX_WMAPE:
        out["accuracy_grade"] = "A"
    elif wmape_dec <= GRADE_B_MAX_WMAPE:
        out["accuracy_grade"] = "B"
    elif wmape_dec <= GRADE_C_MAX_WMAPE:
        out["accuracy_grade"] = "C"
    else:
        out["accuracy_grade"] = "D"

    out["worst_item_id"] = _worst_item(records)
    return out


def _worst_item(records):
    per_item = {}
    for r in records:
        agg = per_item.setdefault(r["item_id"], {"abs": 0, "actual": 0,
                                                 "first": (r["created_at"], r["_seq"])})
        agg["abs"] += r["abs_error_units"]
        agg["actual"] += r["actual_units"]
        key = (r["created_at"], r["_seq"])
        if key < agg["first"]:
            agg["first"] = key

    def sort_key(entry):
        item_id, agg = entry
        if agg["actual"] == 0:
            # items whose records sum to zero actual units rank last
            return (1, D(0), agg["first"][0], agg["first"][1])
        ratio = D(agg["abs"]) / D(agg["actual"])
        return (0, -ratio, agg["first"][0], agg["first"][1])

    return sorted(per_item.items(), key=sort_key)[0][0]
