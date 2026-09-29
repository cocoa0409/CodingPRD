"""Cross-entity services and cascades."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import calc
from errors import ApiError
from store import DB

OPEN_WO_STATES = ("SUBMITTED", "REVISION_REQUESTED", "SCHEDULED")
CREW_BUSY_STATES = ("SCHEDULED", "IN_PROGRESS")
RESERVED_REP_STATES = ("CRANE_RESERVED", "EXECUTED", "CLOSED")


# ---- lookups ---------------------------------------------------------------
def rows(table):
    return DB.all(table)


def turbines_of_farm(farm_id, in_service_only=False):
    out = []
    for t in DB.all("turbines"):
        if t["wind_farm_id"] != farm_id:
            continue
        if in_service_only and t["availability_state"] == "DECOMMISSIONED":
            continue
        out.append(t)
    return out


def farm_of_turbine(turbine):
    return DB.get("farms", turbine["wind_farm_id"])


def model_of_turbine(turbine):
    return DB.get("turbine_models", turbine["turbine_model_id"])


def agreements_of_farm(farm_id, state=None):
    out = []
    for a in DB.all("service_agreements"):
        if a["wind_farm_id"] != farm_id:
            continue
        if state is not None and a["state"] != state:
            continue
        out.append(a)
    return out


def farm_in_settlement(farm_id):
    return any(a["state"] == "IN_SETTLEMENT" for a in agreements_of_farm(farm_id))


def farm_at_risk(farm_id):
    for a in agreements_of_farm(farm_id, "ACTIVE"):
        if a["at_risk_flag"]:
            return True
    return False


def work_orders_of_crew(crew_id, states=CREW_BUSY_STATES):
    return [
        w
        for w in DB.all("work_orders")
        if w["crew_id"] == crew_id and w["state"] in states
    ]


def replacements_of_order(work_order_id):
    return [
        r
        for r in DB.all("component_replacements")
        if r["work_order_id"] == work_order_id
    ]


def replacements_of_crane(crane_id, states=RESERVED_REP_STATES):
    return [
        r
        for r in DB.all("component_replacements")
        if r["crane_mobilization_id"] == crane_id and r["state"] in states
    ]


# ---- derived row figures ---------------------------------------------------
def recompute_service_figures(turbine):
    model = model_of_turbine(turbine)
    due, flag, breached = calc.service_figures(
        turbine["last_service_operating_hours"],
        model["service_interval_hours"],
        model["service_interval_tolerance_hours"],
        turbine["operating_hours"],
    )
    turbine["service_due_operating_hours"] = due
    turbine["service_due_flag"] = flag
    turbine["service_interval_breached"] = breached


def derive_spare_part(part):
    on_hand = part["quantity_on_hand"]
    if on_hand == 0:
        status = "OUT_OF_STOCK"
    elif on_hand < part["reorder_point"]:
        status = "BELOW_REORDER_POINT"
    else:
        status = "IN_STOCK"
    part["status"] = status
    part["procurement_flag"] = status != "IN_STOCK"
    part["total_units_accounted"] = (
        part["quantity_on_hand"] + part["quantity_reserved"] + part["quantity_consumed"]
    )


def recompute_farm_capacity(farm):
    live = turbines_of_farm(farm["id"], in_service_only=True)
    capacity = 0
    for t in live:
        model = model_of_turbine(t)
        capacity += model["rated_power_kw"]
    farm["turbine_count"] = len(live)
    farm["installed_capacity_kw"] = capacity


# ---- farm ledger -----------------------------------------------------------
def post_maintenance_spend(farm, amount_cents):
    if amount_cents == 0:
        return
    farm["maintenance_spend_cents"] = farm["maintenance_spend_cents"] + amount_cents
    farm["opex_accrued_cents"] = farm["opex_accrued_cents"] + amount_cents
    DB.touch(farm)


# ---- availability projection ----------------------------------------------
def live_projection(farm_id):
    """Recompute projected_shortfall_pct and at_risk_flag on ACTIVE agreements."""
    agreements = agreements_of_farm(farm_id, "ACTIVE")
    if not agreements:
        return
    turbine_set = turbines_of_farm(farm_id, in_service_only=True)
    counted = Decimal(0)
    actual_sum = Decimal(0)
    potential_sum = Decimal(0)
    for t in turbine_set:
        counted += Decimal(t["counted_downtime_hours_period"])
        actual_sum += Decimal(t["period_actual_energy_kwh"])
        potential_sum += Decimal(t["period_potential_energy_kwh"])
    for agreement in agreements:
        period_hours = calc.hours_between(
            agreement["period_start_utc"], agreement["period_end_utc"]
        )
        denominator = period_hours * Decimal(len(turbine_set))
        if denominator == 0:
            shortfall = Decimal("0.0000")
        else:
            time_based, energy_based = calc.availability_pcts(
                counted, period_hours, len(turbine_set), actual_sum, potential_sum
            )
            basis = (
                time_based
                if agreement["availability_basis"] == "TIME_BASED"
                else energy_based
            )
            shortfall = calc.shortfall_pct(
                agreement["guaranteed_availability_pct"], basis
            )
        DB.apply(
            agreement,
            {
                "projected_shortfall_pct": shortfall,
                "at_risk_flag": shortfall > 0,
            },
        )


# ---- work order scoring ----------------------------------------------------
def severity_weight_of(work_order):
    work_type = work_order["work_type"]
    if work_type == "MAJOR_COMPONENT":
        return Decimal("1.00")
    if work_type == "SCHEDULED_SERVICE":
        return Decimal("0.30")
    if work_type == "FAULT_DISPATCH":
        event = DB.get("fault_events", work_order["fault_event_id"])
        if event is None:
            return Decimal(0)
        return calc.FAULT_SEVERITY_WEIGHT[event["severity_class_pinned"]]
    damage = DB.get("blade_damages", work_order["blade_damage_id"])
    if damage is None:
        return Decimal(0)
    return Decimal(damage["damage_category"]) / Decimal(5)


def compute_priority_score(work_order):
    turbine = DB.get("turbines", work_order["turbine_id"])
    at_risk = farm_at_risk(turbine["wind_farm_id"])
    days_open = calc.whole_days_elapsed(work_order["created_at"], DB.now())
    return calc.priority_score(
        severity_weight_of(work_order),
        work_order["estimated_hours"],
        turbine["expected_kwh_per_hour"],
        at_risk,
        days_open,
    )


def rescore_farm_work_orders(farm_id, exclude_id=None):
    turbine_ids = set(t["id"] for t in turbines_of_farm(farm_id))
    for wo in DB.all("work_orders"):
        if wo["turbine_id"] not in turbine_ids:
            continue
        if wo["state"] not in OPEN_WO_STATES:
            continue
        if exclude_id is not None and wo["id"] == exclude_id:
            continue
        DB.apply(wo, {"priority_score": compute_priority_score(wo)})


def downtime_changed(farm_id, exclude_wo_id=None):
    """The two-hop propagation shared by every counted-downtime change."""
    live_projection(farm_id)
    rescore_farm_work_orders(farm_id, exclude_id=exclude_wo_id)


# ---- crew and window release ----------------------------------------------
def release_crew(crew):
    if crew is None:
        return
    if work_orders_of_crew(crew["id"]):
        return
    DB.apply(crew, {"status": "AVAILABLE"})


def decrement_window(window, allow_expire):
    if window is None:
        return
    count = window["active_work_order_count"] - 1
    if count < 0:
        count = 0
    window["active_work_order_count"] = count
    if allow_expire and count == 0 and window["state"] == "CONSUMED":
        window["state"] = "EXPIRED"
    DB.touch(window)


def expire_windows():
    """Clock advance: FORECAST/CONFIRMED windows whose end_utc has passed."""
    now = DB.now()
    for w in DB.all("weather_windows"):
        if w["state"] in ("FORECAST", "CONFIRMED") and w["end_utc"] <= now:
            w["state"] = "EXPIRED"
            DB.touch(w)


# ---- fault event closure ---------------------------------------------------
def apply_event_closure(event, turbine):
    """CLEARED -> CLOSED accounting. Mutates both rows without touching them."""
    downtime = calc.hours_between(event["raised_at"], event["cleared_at"])
    lost = calc.rhu(
        Fraction(Decimal(downtime)) * Fraction(Decimal(turbine["expected_kwh_per_hour"])),
        2,
    )
    event["triage_state"] = "CLOSED"
    event["downtime_hours"] = downtime
    event["lost_energy_kwh"] = lost
    turbine["cumulative_lost_energy_kwh"] = (
        Decimal(turbine["cumulative_lost_energy_kwh"]) + lost
    )
    if not event["contractual_exclusion_pinned"]:
        turbine["counted_downtime_hours_period"] = (
            Decimal(turbine["counted_downtime_hours_period"]) + Decimal(downtime)
        )
    return downtime, lost


def close_fault_event(event, turbine, exclude_wo_id=None):
    """CLEARED -> CLOSED plus the three accounting hops."""
    apply_event_closure(event, turbine)
    DB.touch(event)
    DB.touch(turbine)
    downtime_changed(turbine["wind_farm_id"], exclude_wo_id=exclude_wo_id)


# ---- curtailment re-derivation --------------------------------------------
def recompute_curtailment_dimension(turbine):
    active = [
        c
        for c in DB.all("curtailment_orders")
        if c["turbine_id"] == turbine["id"] and c["state"] == "ACTIVE"
    ]
    turbine["active_curtailment_count"] = len(active)
    if not active:
        model = model_of_turbine(turbine)
        turbine["effective_power_limit_kw"] = Decimal(model["rated_power_kw"])
        turbine["curtailment_state"] = "UNCONSTRAINED"
        return
    minimum = min(Decimal(c["power_limit_kw"]) for c in active)
    turbine["effective_power_limit_kw"] = minimum
    turbine["curtailment_state"] = "FORCED_STOP" if minimum == 0 else "CURTAILED"


# ---- crane pricing ---------------------------------------------------------
def crane_reserved_set(crane_id, extra_id=None, exclude_id=None):
    """Reserved replacements of a mobilization, ordered created_at ASC."""
    out = []
    for r in DB.all("component_replacements"):
        if r["id"] == exclude_id:
            continue
        if r["id"] == extra_id:
            out.append(r)
            continue
        if r["crane_mobilization_id"] == crane_id and r["state"] in RESERVED_REP_STATES:
            out.append(r)
    return out


def crane_figures(mob, reserved):
    """Steps 1-8 of crane_cost_and_allocation. Writes nothing."""
    total_lift = Decimal(0)
    for r in reserved:
        total_lift += Decimal(r["estimated_lift_hours"])
    lift_days = calc.crane_lift_days(total_lift)

    dates = calc.utc_dates(mob["mobilization_start_utc"], mob["demobilization_end_utc"])
    limit = Decimal(mob["max_lift_wind_speed_ms"])
    windows = [
        w
        for w in DB.all("weather_windows")
        if w["wind_farm_id"] == mob["wind_farm_id"] and w["state"] == "CONFIRMED"
    ]
    standby_days = 0
    for day_start in dates:
        for w in windows:
            if Decimal(w["forecast_wind_speed_ms"]) > limit and calc.date_contained(
                day_start, w["start_utc"], w["end_utc"]
            ):
                standby_days += 1
                break
    workable_days = len(dates) - standby_days

    billable_days = lift_days + standby_days
    subtotal = mob["mobilization_fee_cents"] + mob["day_rate_cents"] * billable_days
    pct = calc.volume_credit_pct(subtotal)
    credit = calc.rhu_cents(Fraction(subtotal * pct, 100))
    total = subtotal - credit
    shares = calc.waterfall(
        total, [(r["id"], r["estimated_lift_hours"]) for r in reserved]
    )
    return {
        "lift_days": lift_days,
        "standby_days": standby_days,
        "workable_days": workable_days,
        "billable_days": billable_days,
        "subtotal_cents": subtotal,
        "volume_credit_cents": credit,
        "total_crane_cost_cents": total,
        "reserved_replacement_count": len(reserved),
        "shares": shares,
    }


def apply_crane_figures(mob, reserved, figures, skip_id=None):
    """Persist the recomputed mobilization figures and the waterfall shares."""
    mob["lift_days"] = figures["lift_days"]
    mob["standby_days"] = figures["standby_days"]
    mob["billable_days"] = figures["billable_days"]
    mob["subtotal_cents"] = figures["subtotal_cents"]
    mob["volume_credit_cents"] = figures["volume_credit_cents"]
    mob["total_crane_cost_cents"] = figures["total_crane_cost_cents"]
    mob["reserved_replacement_count"] = figures["reserved_replacement_count"]
    for rep in reserved:
        share = figures["shares"].get(rep["id"], 0)
        if rep["id"] == skip_id:
            rep["allocated_crane_cost_cents"] = share
            continue
        DB.apply(rep, {"allocated_crane_cost_cents": share})


# ---- settlement arithmetic -------------------------------------------------
def clipped_downtime(turbine_ids, period_start, period_end):
    counted = Decimal(0)
    for f in DB.all("fault_events"):
        if f["turbine_id"] not in turbine_ids:
            continue
        if f["triage_state"] != "CLOSED" or f["contractual_exclusion_pinned"]:
            continue
        counted += calc.overlap_hours(
            f["raised_at"], f["cleared_at"], period_start, period_end
        )
    for c in DB.all("curtailment_orders"):
        if c["turbine_id"] not in turbine_ids:
            continue
        if c["state"] != "RELEASED" or c["compensable"]:
            continue
        counted += calc.overlap_hours(
            c["start_utc"], c["end_utc"], period_start, period_end
        )
    return counted


def settle_figures(agreement, turbine_set):
    period_start = agreement["period_start_utc"]
    period_end = agreement["period_end_utc"]
    ids = set(t["id"] for t in turbine_set)
    counted = clipped_downtime(ids, period_start, period_end)
    actual_sum = Decimal(0)
    potential_sum = Decimal(0)
    for t in turbine_set:
        actual_sum += Decimal(t["period_actual_energy_kwh"])
        potential_sum += Decimal(t["period_potential_energy_kwh"])
    period_hours = calc.hours_between(period_start, period_end)
    time_based, energy_based = calc.availability_pcts(
        counted, period_hours, len(turbine_set), actual_sum, potential_sum
    )
    basis = (
        time_based if agreement["availability_basis"] == "TIME_BASED" else energy_based
    )
    shortfall = calc.shortfall_pct(agreement["guaranteed_availability_pct"], basis)
    raw_lda = calc.rhu_cents(
        Fraction(Decimal(shortfall))
        * Fraction(int(agreement["lda_rate_cents_per_pct_point"]))
    )
    cap = int(agreement["lda_cap_cents"])
    return time_based, energy_based, shortfall, cap if raw_lda > cap else raw_lda


def royalty_figures(farm, royalty_basis, period_start, period_end, royalty_pct,
                    minimum_payment_cents, energy_price_cents_per_kwh):
    turbine_set = turbines_of_farm(farm["id"], in_service_only=True)
    ids = set(t["id"] for t in turbine_set)
    metered = Decimal(0)
    for t in turbine_set:
        metered += Decimal(t["period_actual_energy_kwh"])
    deemed = Decimal(0)
    if royalty_basis == "DEEMED_INCLUSIVE":
        for c in DB.all("curtailment_orders"):
            if c["turbine_id"] not in ids:
                continue
            if c["state"] != "RELEASED" or not c["compensable"]:
                continue
            hours = calc.overlap_hours(
                c["start_utc"], c["end_utc"], period_start, period_end
            )
            deemed += Decimal(hours) * Decimal(c["deemed_kwh_per_hour"])
    base = metered + deemed
    royalty_cents = calc.rhu_cents(
        Fraction(base)
        * Fraction(Decimal(energy_price_cents_per_kwh))
        * Fraction(Decimal(royalty_pct))
        / Fraction(100)
    )
    payment = int(minimum_payment_cents)
    if royalty_cents > payment:
        payment = royalty_cents
    road_levy = calc.rhu_cents(
        Fraction(payment) * Fraction(Decimal(farm["road_levy_pct"])) / Fraction(100)
    )
    community_levy = calc.rhu_cents(
        Fraction(payment) * Fraction(Decimal(farm["community_levy_pct"])) / Fraction(100)
    )
    return metered, deemed, royalty_cents, payment, road_levy, community_levy


def post_settlement(farm, settlement, sign):
    payment = int(settlement["payment_cents"])
    road = int(settlement["road_levy_cents"]) + int(
        settlement["road_damage_assessment_cents"]
    )
    community = int(settlement["community_levy_cents"])
    farm["landowner_payable_cents"] = farm["landowner_payable_cents"] + sign * payment
    farm["road_maintenance_reserve_cents"] = (
        farm["road_maintenance_reserve_cents"] + sign * road
    )
    farm["community_fund_balance_cents"] = (
        farm["community_fund_balance_cents"] + sign * community
    )
    farm["opex_accrued_cents"] = farm["opex_accrued_cents"] + sign * (
        payment + road + community
    )
    DB.touch(farm)


# ---- replacement cancellation cascade --------------------------------------
def cancel_replacement(rep):
    """The four hops shared by direct cancellation and the work-order cascade."""
    part = DB.get("spare_parts", rep["spare_part_id"])
    crane_id = rep["crane_mobilization_id"]
    held_crane = rep["state"] == "CRANE_RESERVED" and crane_id is not None

    # hop 1
    rep["state"] = "CANCELLED"
    rep["allocated_crane_cost_cents"] = 0
    rep["execution_path"] = None
    DB.touch(rep)

    # hop 2
    if part is not None:
        part["quantity_reserved"] = part["quantity_reserved"] - 1
        part["quantity_on_hand"] = part["quantity_on_hand"] + 1
        derive_spare_part(part)
        DB.touch(part)

    # hop 3
    if held_crane:
        mob = DB.get("crane_mobilizations", crane_id)
        if mob is not None:
            survivors = crane_reserved_set(crane_id)
            if not survivors and mob["state"] == "MOBILIZED":
                fee = calc.rhu_cents(
                    Fraction(int(mob["mobilization_fee_cents"]) * calc.CRANE_CANCELLATION_PCT, 100)
                )
                mob["reserved_replacement_count"] = 0
                mob["billable_days"] = 0
                mob["state"] = "CANCELLED"
                mob["total_crane_cost_cents"] = fee
                DB.touch(mob)
                post_maintenance_spend(DB.get("farms", mob["wind_farm_id"]), fee)
            else:
                figures = crane_figures(mob, survivors)
                apply_crane_figures(mob, survivors, figures)
                DB.touch(mob)

    # hop 4
    parent = DB.get("work_orders", rep["work_order_id"])
    if parent is not None and parent["state"] == "SCHEDULED":
        window = DB.get("weather_windows", parent["weather_window_id"])
        crew = DB.get("crews", parent["crew_id"])
        parent["state"] = "REVISION_REQUESTED"
        parent["revision_round"] = int(parent["revision_round"]) + 1
        parent["crew_id"] = None
        parent["weather_window_id"] = None
        parent["planned_start_utc"] = None
        parent["planned_end_utc"] = None
        DB.touch(parent)
        decrement_window(window, allow_expire=False)
        release_crew(crew)
