"""The seven declared calculations (PRD section 1.3)."""

from datetime import timedelta
from decimal import Decimal

import consts
import derive
import store
from util import (
    ceil_int,
    dec,
    fixed,
    floor_int,
    half_up_int,
    overlap_minutes,
    round_half_up,
    whole_minutes,
)


# ---------------------------------------------------------------------------
# 1. time_band_pax_forecast
# ---------------------------------------------------------------------------
def projected_pax(flight):
    return half_up_int(dec(flight["seats_sold"]) * dec(flight["load_factor_pct"]) / dec(100))


def forecast_flights(checkpoint_id):
    rows = [
        f
        for f in store.rows("flight_schedule_entries")
        if f["checkpoint_id"] == checkpoint_id and f["status"] == "SCHEDULED"
    ]
    rows.sort(key=lambda f: (f["scheduled_departure_utc"], f["flight_number"]))
    return rows


def time_band_pax_forecast(band, variant):
    checkpoint = store.get("checkpoints", band["checkpoint_id"])
    b_start = band["band_start_utc"]
    b_end = band["band_end_utc"]
    total = 0
    for flight in forecast_flights(band["checkpoint_id"]):
        pax = dec(projected_pax(flight))
        curve = store.get("show_up_curves", flight["show_up_curve_id"])
        if curve is None:
            continue
        departure = flight["scheduled_departure_utc"]
        if variant == "SCHEDULE_ONLY":
            w0 = departure - timedelta(minutes=curve["window_start_minutes_before"])
            w1 = departure - timedelta(minutes=curve["window_end_minutes_before"])
            span = curve["window_start_minutes_before"] - curve["window_end_minutes_before"]
            if span <= 0:
                continue
            minutes = overlap_minutes(b_start, b_end, w0, w1)
            contrib = pax * dec(minutes) / dec(span)
        else:
            contrib = Decimal(0)
            buckets = sorted(
                curve["buckets"], key=lambda b: b["minutes_before_start"], reverse=True
            )
            for bucket in buckets:
                b0 = departure - timedelta(minutes=bucket["minutes_before_start"])
                b1 = departure - timedelta(minutes=bucket["minutes_before_end"])
                b_span = bucket["minutes_before_start"] - bucket["minutes_before_end"]
                if b_span <= 0:
                    continue
                minutes = overlap_minutes(b_start, b_end, b0, b1)
                contrib += (
                    pax * (dec(bucket["share_pct"]) / dec(100)) * dec(minutes) / dec(b_span)
                )
            discount = dec(checkpoint["connecting_pax_discount_pct"])
            contrib = contrib * (dec(1) - discount / dec(100))
            contrib = contrib * dec(band["seasonal_multiplier"])
        total += half_up_int(contrib)
    return total


# ---------------------------------------------------------------------------
# 2. lane_requirement
# ---------------------------------------------------------------------------
def lane_candidates(checkpoint_id, lane_type):
    rows = [
        l
        for l in store.rows("lanes")
        if l["checkpoint_id"] == checkpoint_id
        and l["lane_type"] == lane_type
        and l["lane_state"] in ("CLOSED", "OPEN", "PAUSED")
    ]
    rows.sort(key=lambda l: (l["position_index"], l["_seq"]))
    return rows


def lane_capacity(lane, posture, apply_surge=True):
    equipment_state = derive.lane_equipment_state(lane)
    if equipment_state == "OUT_OF_SERVICE":
        return 0
    value = dec(consts.LANE_BASE_THROUGHPUT_PPH[lane["lane_type"]])
    value = value * dec(consts.BAND_MINUTES) / dec(60)
    if equipment_state == "DEGRADED":
        value = value * consts.DEGRADED_EQUIPMENT_FACTOR
    if apply_surge and posture == "SURGE":
        value = value * consts.SURGE_POSTURE_DERATE
    return floor_int(value)


def lane_requirement(band):
    checkpoint = store.get("checkpoints", band["checkpoint_id"])
    posture = derive.posture(checkpoint)
    demand_total = band["forecast_pax_count"] or 0
    expedited_demand = ceil_int(dec(demand_total) * dec(band["expedited_share_pct"]) / dec(100))
    standard_demand = demand_total - expedited_demand
    out = {}
    for lane_type, demand in (("STANDARD", standard_demand), ("EXPEDITED", expedited_demand)):
        candidates = lane_candidates(band["checkpoint_id"], lane_type)
        cumulative = 0
        consumed = 0
        for lane in candidates:
            if cumulative >= demand:
                break
            cumulative += lane_capacity(lane, posture)
            consumed += 1
        required = max(consts.MIN_OPEN_LANES[lane_type], consumed)
        required = min(required, len(candidates))
        out[lane_type] = (required, max(0, demand - cumulative))
    return {
        "required_standard_lanes": out["STANDARD"][0],
        "required_expedited_lanes": out["EXPEDITED"][0],
        "unmet_standard_demand": out["STANDARD"][1],
        "unmet_expedited_demand": out["EXPEDITED"][1],
    }


# ---------------------------------------------------------------------------
# 3. officer_duty_ledger
# ---------------------------------------------------------------------------
def officer_duty_ledger(officer, variant, extra_minutes=0, extra_detail_minutes=0):
    assignments = derive.officer_assignments(officer["id"])
    worked = 0
    if variant == "CHRONOLOGICAL_ACTUAL":
        rows = [a for a in assignments if a["assignment_state"] in ("CHECKED_IN", "RELEASED")]
        rows.sort(key=lambda a: (a["checked_in_at_utc"] or store.now(), a["_seq"]))
        for row in rows:
            if row["checked_in_at_utc"] is None:
                continue
            end = row["released_at_utc"] or store.now()
            elapsed = whole_minutes(row["checked_in_at_utc"], end)
            worked += max(0, elapsed - row["break_minutes_taken"])
    else:
        for row in assignments:
            if row["assignment_state"] in ("SCHEDULED", "CHECKED_IN", "RELEASED"):
                worked += row["planned_minutes"]
    worked += extra_minutes
    detail_minutes = derive.approved_detail_minutes(officer["id"]) + extra_detail_minutes
    total = worked + detail_minutes
    regular = min(total, officer["weekly_regular_minutes_cap"])
    overtime = max(0, total - officer["weekly_regular_minutes_cap"])
    return {
        "officer_id": officer["id"],
        "variant": variant,
        "worked_minutes": worked,
        "approved_detail_minutes": detail_minutes,
        "total_minutes": total,
        "regular_minutes": regular,
        "overtime_minutes": overtime,
        "cap_headroom_minutes": officer["weekly_overtime_minutes_cap"] - overtime,
    }


# ---------------------------------------------------------------------------
# 4. staffing_plan_cost
# ---------------------------------------------------------------------------
def plan_assignments(plan_id, states=("SCHEDULED", "CHECKED_IN", "RELEASED")):
    return [
        a
        for a in store.rows("lane_assignments")
        if a["staffing_plan_id"] == plan_id and a["assignment_state"] in states
    ]


def plan_details(plan_id, state="APPROVED"):
    return [
        d
        for d in store.rows("surge_details")
        if d["staffing_plan_id"] == plan_id and d["state"] == state
    ]


def admin_fee_rate_for(subtotal_cents):
    if subtotal_cents < consts.ADMIN_FEE_TIER_1_MAX_EXCLUSIVE:
        return consts.ADMIN_FEE_TIER_1_RATE
    if subtotal_cents < consts.ADMIN_FEE_TIER_2_MAX_EXCLUSIVE:
        return consts.ADMIN_FEE_TIER_2_RATE
    return consts.ADMIN_FEE_TIER_3_RATE


def staffing_plan_cost(plan, extra_detail_minutes=0):
    minutes_by_officer = {}
    for row in plan_assignments(plan["id"]):
        minutes_by_officer[row["officer_id"]] = (
            minutes_by_officer.get(row["officer_id"], 0) + row["planned_minutes"]
        )
    officers = []
    for officer_id, minutes in minutes_by_officer.items():
        officer = store.get("officers", officer_id)
        if officer is None:
            continue
        officers.append((officer, minutes))
    officers.sort(key=lambda pair: pair[0]["badge_number"])

    planned_regular = 0
    planned_overtime = 0
    base_cost = 0
    overtime_cost = 0
    breakdown = []
    for officer, minutes in officers:
        regular = min(minutes, officer["weekly_regular_minutes_cap"])
        overtime = max(0, minutes - officer["weekly_regular_minutes_cap"])
        officer_base = half_up_int(dec(regular) * dec(officer["base_rate_cents_per_minute"]))
        officer_ot = half_up_int(
            dec(overtime) * dec(officer["base_rate_cents_per_minute"]) * consts.OVERTIME_MULTIPLIER
        )
        planned_regular += regular
        planned_overtime += overtime
        base_cost += officer_base
        overtime_cost += officer_ot
        breakdown.append(
            {
                "officer_id": officer["id"],
                "badge_number": officer["badge_number"],
                "planned_minutes": minutes,
                "regular_minutes": regular,
                "overtime_minutes": overtime,
                "base_cost_cents": officer_base,
                "overtime_cost_cents": officer_ot,
            }
        )

    detail_minutes = sum(d["detail_minutes"] for d in plan_details(plan["id"]))
    detail_minutes += extra_detail_minutes
    detail_cost = detail_minutes * consts.DETAIL_RATE_CENTS_PER_MINUTE
    subtotal = base_cost + overtime_cost + detail_cost
    rate = admin_fee_rate_for(subtotal)
    admin_fee = half_up_int(dec(subtotal) * rate)
    return {
        "planned_regular_minutes": planned_regular,
        "planned_overtime_minutes": planned_overtime,
        "base_cost_cents": base_cost,
        "overtime_cost_cents": overtime_cost,
        "detail_cost_cents": detail_cost,
        "subtotal_cents": subtotal,
        "admin_fee_rate": fixed(rate, 3),
        "admin_fee_cents": admin_fee,
        "total_cost_cents": subtotal + admin_fee,
        "officer_breakdown": breakdown,
        "_has_assignments": bool(officers),
    }


COST_FIELDS = (
    "planned_regular_minutes",
    "planned_overtime_minutes",
    "base_cost_cents",
    "overtime_cost_cents",
    "detail_cost_cents",
    "subtotal_cents",
    "admin_fee_rate",
    "admin_fee_cents",
    "total_cost_cents",
)


def apply_plan_cost(plan):
    """Persist the cost fields after a write that changes the plan's assignments.

    PRD 3.3 makes assignment creation "recompute the owning plan's cost", and
    restates that "the same computation is re-run on every later write that
    changes the plan's assignments or its approved details".  Neither sentence
    is conditioned on the plan having been submitted, so a DRAFT plan that holds
    assignments carries a live price too -- only a plan with no assignments (on
    create) or one rewound by a revise has nothing to price.
    """
    if plan["state"] not in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVATED"):
        return
    result = staffing_plan_cost(plan)
    for field in COST_FIELDS:
        plan[field] = result[field]


# ---------------------------------------------------------------------------
# 5. published_wait_time
# ---------------------------------------------------------------------------
def threshold_for(checkpoint, lane_type):
    if lane_type == "EXPEDITED":
        return checkpoint["wait_threshold_minutes_expedited"]
    return checkpoint["wait_threshold_minutes_standard"]


def publication_window():
    end = store.now()
    return end - timedelta(minutes=consts.PUBLICATION_WINDOW_MINUTES), end


def published_wait_time(checkpoint, lane_type):
    window_start, window_end = publication_window()
    samples = [
        o
        for o in store.rows("wait_time_observations")
        if o["checkpoint_id"] == checkpoint["id"]
        and o["lane_type"] == lane_type
        and window_start <= o["observed_at_utc"] <= window_end
    ]
    threshold = threshold_for(checkpoint, lane_type)
    result = {
        "checkpoint_id": checkpoint["id"],
        "lane_type": lane_type,
        "published_wait_minutes": None,
        "weighted_average_seconds": None,
        "sample_count": len(samples),
        "threshold_minutes": threshold,
        "breached": False,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
    }
    if not samples:
        return result
    if len(samples) < consts.MIN_SAMPLES_FOR_WEIGHTED_AVERAGE:
        latest = sorted(samples, key=lambda o: (o["observed_at_utc"], o["_seq"]))[-1]
        average = round_half_up(dec(latest["sampled_wait_seconds"]), 2)
    else:
        weighted_sum = Decimal(0)
        weight_total = Decimal(0)
        for sample in samples:
            weight = dec(consts.METHOD_WEIGHTS[sample["measurement_method"]]) * dec(
                sample["sample_size"]
            )
            weighted_sum += weight * dec(sample["sampled_wait_seconds"])
            weight_total += weight
        average = round_half_up(weighted_sum / weight_total, 2)
    minutes = half_up_int(average / dec(60))
    result["weighted_average_seconds"] = fixed(average, 2)
    result["published_wait_minutes"] = minutes
    result["breached"] = minutes >= threshold
    return result


# ---------------------------------------------------------------------------
# 7. throughput_and_diversion_index
# ---------------------------------------------------------------------------
def served_capacity_pax(checkpoint_id):
    total = 0
    for lane in derive.checkpoint_lanes(checkpoint_id):
        if lane["lane_state"] != "OPEN":
            continue
        total += lane_capacity(lane, "NORMAL", apply_surge=False)
    return total


def throughput_and_diversion_index(checkpoint):
    bands = [
        b
        for b in store.rows("time_bands")
        if b["checkpoint_id"] == checkpoint["id"] and b["forecast_pax_count"] is not None
    ]
    bands.sort(key=lambda b: (b["band_start_utc"], b["_seq"]))
    served = served_capacity_pax(checkpoint["id"])
    results = []
    total_forecast = 0
    best_run = 0
    run = 0
    for band in bands:
        forecast = band["forecast_pax_count"]
        total_forecast += forecast
        shortfall = forecast > 0 and (
            dec(served) < consts.THROUGHPUT_SHORTFALL_RATIO * dec(forecast)
        )
        if shortfall:
            run += 1
            best_run = max(best_run, run)
        else:
            run = 0
        results.append(
            {
                "time_band_id": band["id"],
                "band_start_utc": band["band_start_utc"],
                "band_end_utc": band["band_end_utc"],
                "forecast_pax_count": forecast,
                "served_capacity_pax": served,
                "shortfall": shortfall,
            }
        )
    if total_forecast == 0:
        rate = Decimal("0.0000")
    else:
        rate = round_half_up(dec(checkpoint["diverted_pax_total"]) / dec(total_forecast), 4)
    return {
        "checkpoint_id": checkpoint["id"],
        "total_forecast_pax": total_forecast,
        "band_results": results,
        "max_consecutive_shortfall_bands": best_run,
        "diverted_pax_total": checkpoint["diverted_pax_total"],
        "diversion_rate": fixed(rate, 4),
        "design_change_recommended": (
            rate >= consts.DIVERSION_RATE_DESIGN_THRESHOLD
            and best_run >= consts.CONSECUTIVE_SHORTFALL_BANDS_REQUIRED
        ),
    }
