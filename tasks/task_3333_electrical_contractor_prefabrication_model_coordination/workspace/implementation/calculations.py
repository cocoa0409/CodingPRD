"""Every algorithmic rule from the scaffold ``calculations`` table.

Formulas follow PRD.md §3 verbatim.  All money is handled as whole cents and all
hours as plain numbers, with round-half-up applied at the precision the PRD
states for each figure.
"""

from core import (CLOCK, DB, ceil_int, dec, num, rhu, shift_days, to_dt,
                  whole_days_between)

# --------------------------------------------------------------------------
# Constants read from the scaffold's calculations table
# --------------------------------------------------------------------------

CHAIN_PENALTY = {"CHAIN_DEPENDENT": 1.2, "PARALLEL_FABRICATION": 1.0}
SUPPORTED_DERATE = 1.0

STAGE_WINDOW = {
    "FIRST_STAGE": {"clash_slots": 4, "trade_count": 2},
    "SECOND_STAGE": {"clash_slots": 3, "trade_count": 1},
    "TRIM_OUT": {"clash_slots": 2, "trade_count": 0},
}
SHOP_CAPACITY_LADDER = [
    {"shop_utilisation_pct_max": 0.85, "multiplier": 1.0},
    {"shop_utilisation_pct_max": 1.00, "multiplier": 1.2},
    {"shop_utilisation_pct_max": None, "multiplier": 1.5},
]
RACK_STAGING_DURATION_FACTOR = 3
INSTALL_PRODUCTIVITY_FLOOR = 0.40
MIN_HOISTING_DAYS = 1
MAX_HOISTING_DAYS = 10

RACK_CAPACITY_MARGIN = 0.95

TAKEOFF_DEPTH_LADDER = [
    {"depth_max": 1, "multiplier": 1.0},
    {"depth_max": 3, "multiplier": 1.15},
    {"depth_max": None, "multiplier": 1.35},
]

APPLIANCE_LAG = {
    "SWITCHGEAR": {"travel_days": 2, "unload_days": 2},
    "MC_CABLE": {"travel_days": 1, "unload_days": 1},
    "EMT_CONDUIT": {"travel_days": 1, "unload_days": 1},
    "RIGID_CONDUIT": {"travel_days": 1, "unload_days": 1},
    "STRUT": {"travel_days": 1, "unload_days": 1},
    "FITTINGS": {"travel_days": 1, "unload_days": 1},
    "WIRE": {"travel_days": 1, "unload_days": 1},
    "BOX": {"travel_days": 1, "unload_days": 1},
}
DEFAULT_SHOP_TAT_DAYS = 2

OVERTIME_MULTIPLIER = 1.5

APPRENTICE_TIER_DEFAULT = {
    "APPRENTICE_PERIODS_1_2": 1.0,
    "APPRENTICE_PERIODS_3_4": 0.5,
    "APPRENTICE_PERIOD_5": 0.5,
}
WAIT_TIER_DEFAULT = dict(APPRENTICE_TIER_DEFAULT)

APPLICABLE_CONTRACT_HOURS = 8000.0

VALUE_CLASSIFICATION = "JOURNEYMAN"

REVISION_SCOPE_DIVISOR = 4
KLUDGE_RATE_PER_HOUR_CENTS = 8500
NEGOTIATED_RATE_PER_HOUR_CENTS = 7800
SUBMITTED_MARKUP_PCT = 0.18
SHOP_PARTS_BASIS_CENTS = 12000

FACTOR_TABLE = {True: 11, False: 16}
IDLE_WEIGHT_LADDER = [
    {"weight_floor_pct": 0.70, "multiplier": 0.85},
    {"weight_floor_pct": 0.85, "multiplier": 0.75},
    {"weight_floor_pct": None, "multiplier": 0.60},
]

PKG_SET = "task_3333_electrical_contractor_prefabrication_model_coordination"


# --------------------------------------------------------------------------
# Assembly lookups
# --------------------------------------------------------------------------

def get_assembly(assembly_code):
    return DB.find("assemblies", assembly_code)


def prefab_hours_per_unit(assembly, conduit_run_type_code):
    """Ideal conduit codes use the nominal per-unit hours; otherwise the derate."""
    if assembly is None:
        return 0.0
    base = num(assembly.get("prefab_hours_per_unit"), 0.0)
    ideal = assembly.get("ideal_conduit_type_codes") or []
    if conduit_run_type_code in ideal:
        return base
    return base * SUPPORTED_DERATE


def run_factor(assembly, conduit_run_type):
    factors = (assembly or {}).get("conduit_labor_factors") or {}
    return num(factors.get(conduit_run_type), 1.0)


# --------------------------------------------------------------------------
# conduit_craft_hours / conduit_run_impact
# --------------------------------------------------------------------------

def consuming_component(takeoff_line_id):
    for component in DB.all("prefab_components"):
        if component.get("takeoff_line_id") == takeoff_line_id:
            return component
    return None


def conduit_craft_hours(line):
    """Two-decimal shop hours for an extracted line, zero once superseded."""
    if line.get("status") == "SUPERSEDED":
        return 0.0
    assembly = get_assembly(line.get("assembly_code"))
    if assembly is None:
        return 0.0
    per_unit = rhu(prefab_hours_per_unit(assembly, line.get("conduit_run_type_code")), 2)
    base = per_unit * num(line.get("quantity"), 0.0)
    factor = run_factor(assembly, line.get("conduit_run_type"))
    component = consuming_component(line["id"])
    if component is None:
        penalty = 1.0
    else:
        penalty = CHAIN_PENALTY.get(component.get("chain_mode"), 1.0)
    return rhu(base * factor * penalty, 2)


def conduit_run_impact(line, run_depth=1):
    """Tiered billed hours per line; superseded lines bill zero."""
    if line.get("status") == "SUPERSEDED":
        return 0.0
    assembly = get_assembly(line.get("assembly_code"))
    if assembly is None:
        return 0.0
    factor = run_factor(assembly, line.get("conduit_run_type"))
    multiplier = 1.0
    for row in TAKEOFF_DEPTH_LADDER:
        if row["depth_max"] is None or run_depth <= row["depth_max"]:
            multiplier = row["multiplier"]
            break
    billed = (num(line.get("quantity"), 0.0)
              * num(assembly.get("prefab_hours_per_unit"), 0.0)
              * factor * multiplier)
    return rhu(billed, 2)


# --------------------------------------------------------------------------
# rack_value_capacity_check
# --------------------------------------------------------------------------

RACK_COUNTED_STATUSES = ("PLANNED", "FABRICATED", "LOADED", "REWORK", "SCRAPPED")


def rack_components(rack_id):
    return [c for c in DB.all("prefab_components") if c.get("rack_id") == rack_id]


def rack_value_capacity_check(rack):
    total = 0.0
    for component in rack_components(rack["id"]):
        if component.get("install_status") in RACK_COUNTED_STATUSES:
            total += num(component.get("quantity"), 0.0)
    rack["reserved_streams_and_phase_cf"] = rhu(total, 4)
    return rack["reserved_streams_and_phase_cf"]


def rack_capacity_ok(rack):
    reserved = rack_value_capacity_check(rack)
    capacity = num(rack.get("value_capacity_cf"), 0.0)
    return reserved <= RACK_CAPACITY_MARGIN * capacity


# --------------------------------------------------------------------------
# hoisting_window_derivation
# --------------------------------------------------------------------------

def project_installed_pct(project):
    return num(project.get("installed_pct"), 0.0)


def hoisting_window_derivation(order, project):
    stage = STAGE_WINDOW.get(order.get("stage_code"), {"clash_slots": 0, "trade_count": 0})
    chain_depth = 0
    for component in DB.all("prefab_components"):
        if component.get("prefab_order_id") != order["id"]:
            continue
        predecessor_id = component.get("predecessor_component_id")
        if not predecessor_id:
            continue
        predecessor = DB.find("prefab_components", predecessor_id)
        if predecessor is None or predecessor.get("install_status") != "SET":
            chain_depth += 1
    penalty = 0 if project_installed_pct(project) >= INSTALL_PRODUCTIVITY_FLOOR else 1
    utilisation = num(project.get("shop_utilization_pct"), 0.0)
    multiplier = 1.5
    for row in SHOP_CAPACITY_LADDER:
        if row["shop_utilisation_pct_max"] is None or utilisation <= row["shop_utilisation_pct_max"]:
            multiplier = row["multiplier"]
            break
    raw = (stage["clash_slots"] + stage["trade_count"] + chain_depth + penalty) * multiplier
    base_days = ceil_int(raw)
    duration = max(MIN_HOISTING_DAYS, min(base_days, MAX_HOISTING_DAYS))
    power_on = to_dt(project.get("power_on_iso"))
    assembly_count = int(order.get("assembly_count") or 0)
    staging = ceil_int(assembly_count * RACK_STAGING_DURATION_FACTOR)
    if power_on is not None:
        start = shift_days(power_on, -(base_days + staging))
    else:
        start = None
    end = shift_days(start, duration) if start is not None else None
    return {
        "base_days": base_days,
        "hoisting_duration_days": duration,
        "hoisting_start": start,
        "hoisting_end": end,
    }


# --------------------------------------------------------------------------
# material_release_timing
# --------------------------------------------------------------------------

def earliest_shop_release_iso(project_id):
    stamps = []
    for order in DB.all("prefab_orders"):
        if order.get("project_id") != project_id:
            continue
        stamp = order.get("release_to_shop_iso")
        if stamp:
            stamps.append(to_dt(stamp))
    if not stamps:
        return None
    return min(stamps)


def material_release_timing(release, project):
    lag = APPLIANCE_LAG.get(release.get("material_commodity"), {"travel_days": 1, "unload_days": 1})
    power_on = to_dt(project.get("power_on_iso"))
    if power_on is None:
        return release
    required_on_site = shift_days(power_on, -lag["travel_days"])
    lead = num(release.get("lead_time_days"), 0)
    planned_delivery = shift_days(required_on_site, -(lead + lag["unload_days"]))
    planned_release = shift_days(planned_delivery, -DEFAULT_SHOP_TAT_DAYS)
    release["derived_required_on_site_iso"] = planned_delivery and required_on_site
    release["derived_planned_delivery_iso"] = planned_delivery
    release["derived_planned_release_iso"] = planned_release
    release["priced_hours"] = rhu(num(release.get("quantity"), 0.0) * lead, 2)
    earliest = earliest_shop_release_iso(project["id"])
    if earliest is not None:
        release["locked_release_iso"] = planned_release if planned_release <= earliest else earliest
    elif release.get("locked_release_iso") is None and release.get("status") == "RELEASED":
        release["locked_release_iso"] = planned_release
    return release


# --------------------------------------------------------------------------
# project_pipeline_balance
# --------------------------------------------------------------------------

def project_orders(project_id):
    return [o for o in DB.all("prefab_orders") if o.get("project_id") == project_id]


def project_components(project_id):
    order_ids = {o["id"] for o in project_orders(project_id)}
    return [c for c in DB.all("prefab_components") if c.get("prefab_order_id") in order_ids]


def component_crafted_hours(component):
    assembly = get_assembly(component.get("assembly_code"))
    if assembly is None:
        return 0.0
    return rhu(num(component.get("quantity"), 0.0) * num(assembly.get("prefab_hours_per_unit"), 0.0), 2)


def component_prefab_value(component, project):
    from projects import project_journeyman_rate
    hours = component_crafted_hours(component)
    rate = project_journeyman_rate(project)
    return rhu(hours * num(rate.get("hourly_rate_cents"), 0) * (1 + num(rate.get("burden_pct"), 0.0)), 0)


def update_project_pipeline(project):
    """Recompute man hours, component values and both value balances."""
    components = project_components(project["id"])
    man_hours = 0.0
    pipeline = 0
    completed = 0
    for component in components:
        component["crafted_hours"] = component_crafted_hours(component)
        man_hours += component["crafted_hours"]
        value = component_prefab_value(component, project)
        component["prefab_value_cents"] = value
        status = component.get("install_status")
        if status == "SET":
            completed += value
        elif status in ("PLANNED", "FABRICATED", "LOADED", "REWORK"):
            pipeline += value
    project["man_hours_total"] = rhu(man_hours, 2)
    project["pipeline_value_cents"] = int(pipeline)
    project["completed_value_cents"] = int(completed)
    denom = pipeline + completed
    project["installed_pct"] = rhu(completed / float(denom), 4) if denom > 0 else 0.0
    total_hours = num(project.get("man_hours_total"), 0.0)
    factor = FACTOR_TABLE[project["installed_pct"] >= INSTALL_PRODUCTIVITY_FLOOR]
    project["effective_flow_pct"] = rhu(rhu(total_hours * factor, 0) / float(max(total_hours, 1)), 4)
    return project


# --------------------------------------------------------------------------
# craft_hours_credit / craft_hours_balance
# --------------------------------------------------------------------------

def craft_hours_credit(project):
    man_hours = num(project.get("man_hours_total"), 0.0)
    total_quantity = num(project.get("total_quantity"), 0.0)
    released_quantity = num(project.get("released_quantity"), 0.0)
    if total_quantity > 0:
        expected_released = man_hours * (released_quantity / total_quantity)
    else:
        expected_released = 0.0
    project["craft_hours_credit"] = rhu(max(0.0, man_hours - expected_released), 2)
    for order in project_orders(project["id"]):
        total = sum(component_crafted_hours(c) for c in
                    DB.all("prefab_components") if c.get("prefab_order_id") == order["id"])
        if order.get("release_to_shop_iso"):
            order["crafted_hours_credit"] = 0.0
        else:
            order["crafted_hours_credit"] = rhu(total, 2)
    return project["craft_hours_credit"]


def craft_hours_balance(project):
    from projects import project_journeyman_rate
    rate = num(project_journeyman_rate(project).get("hourly_rate_cents"), 0)
    man_hours = num(project.get("man_hours_total"), 0.0)
    base_labor = rhu(man_hours * rate, 0)
    material_hours = sum(
        component_crafted_hours(c) for c in project_components(project["id"])
        if c.get("install_status") != "SCRAPPED"
    )
    base_material = rhu(material_hours * rate, 0)
    project["craft_hours_balance"] = int(base_labor + base_material)
    return project["craft_hours_balance"]


# --------------------------------------------------------------------------
# idle_capacity_writeoff
# --------------------------------------------------------------------------

def idle_capacity(project):
    from projects import project_journeyman_rate
    man_hours = num(project.get("man_hours_total"), 0.0)
    if man_hours <= 0:
        project["idle_capacity_cents"] = 0
        return 0
    utilisation = num(project.get("shop_utilization_pct"), 0.0)
    multiplier = 0.60
    for row in IDLE_WEIGHT_LADDER:
        if row["weight_floor_pct"] is None or utilisation <= row["weight_floor_pct"]:
            multiplier = row["multiplier"]
            break
    rate = num(project_journeyman_rate(project).get("hourly_rate_cents"), 0)
    value = man_hours * rate * multiplier * (1 - num(project.get("installed_pct"), 0.0))
    project["idle_capacity_cents"] = rhu(value, 0)
    return project["idle_capacity_cents"]


# --------------------------------------------------------------------------
# gross_payroll_reconciliation
# --------------------------------------------------------------------------

def crew_day_labor_cost(crew_day):
    from projects import rate_for
    worker = DB.find("workers", crew_day.get("worker_id"))
    if worker is None:
        return 0
    rate = rate_for(worker.get("home_jurisdiction_key"), worker.get("classification"),
                    worker.get("apprentice_period"), crew_day.get("work_date_iso"))
    hours = num(crew_day.get("regular_hours"), 0.0) + OVERTIME_MULTIPLIER * num(crew_day.get("overtime_hours"), 0.0)
    return rhu(hours * num(rate.get("hourly_rate_cents"), 0) * (1 + num(rate.get("burden_pct"), 0.0)), 0)


def crew_day_adjusted_cost(crew_day, project):
    from projects import rate_for
    rate = rate_for(project.get("jurisdiction_key"), VALUE_CLASSIFICATION, None, crew_day.get("work_date_iso"))
    hours = num(crew_day.get("regular_hours"), 0.0) + OVERTIME_MULTIPLIER * num(crew_day.get("overtime_hours"), 0.0)
    return rhu(hours * num(rate.get("hourly_rate_cents"), 0) * (1 + num(rate.get("burden_pct"), 0.0)), 0)


def gross_payroll_reconciliation(ledger_row, project):
    rows = [
        day for day in DB.all("crew_days")
        if day.get("worker_id") == ledger_row.get("worker_id")
        and day.get("trade_activity_id") == ledger_row.get("trade_activity_id")
        and day.get("project_id") == ledger_row.get("project_id")
    ]
    total = 0
    gross = 0
    adjusted = 0
    for day in rows:
        day["labor_cost_cents"] = crew_day_labor_cost(day)
        day["adjusted_value_cents"] = crew_day_adjusted_cost(day, project)
        gross += day["labor_cost_cents"]
        adjusted += day["adjusted_value_cents"]
        if day.get("accepted_for_credit"):
            total += day["labor_cost_cents"]
    ledger_row["total_cents"] = int(total)
    ledger_row["gross_payroll_cents"] = int(gross)
    ledger_row["adjusted_payroll_cents"] = int(adjusted)
    return ledger_row


# --------------------------------------------------------------------------
# field_credit_policy
# --------------------------------------------------------------------------

def field_credit_policy(project, worker_id, work_date_iso):
    policy = project.get("credit_policy") or "FIRST_ACCEPTED"
    candidates = [
        day for day in DB.all("crew_days")
        if day.get("project_id") == project["id"]
        and day.get("worker_id") == worker_id
        and day.get("work_date_iso") == work_date_iso
        and int(day.get("report_sequence") or 0) >= 1
    ]
    for day in candidates:
        day["accepted_for_credit"] = False
        day["credited_hours"] = 0.0
    if not candidates:
        return None
    if policy == "FIRST_ACCEPTED":
        candidates.sort(key=lambda d: (int(d.get("report_sequence") or 0), d.get("created_at") or ""))
    else:
        candidates.sort(key=lambda d: (-(num(d.get("regular_hours"), 0.0) + OVERTIME_MULTIPLIER * num(d.get("overtime_hours"), 0.0)),
                                       int(d.get("report_sequence") or 0)))
    winner = candidates[0]
    winner["accepted_for_credit"] = True
    winner["credited_hours"] = rhu(num(winner.get("regular_hours"), 0.0)
                                   + OVERTIME_MULTIPLIER * num(winner.get("overtime_hours"), 0.0), 2)
    return winner


# --------------------------------------------------------------------------
# ratio_limit_resolution
# --------------------------------------------------------------------------

def ring_band(apprentice_period):
    period = apprentice_period
    try:
        period = int(period)
    except (TypeError, ValueError):
        return None
    if period in (1, 2):
        return "APPRENTICE_PERIODS_1_2"
    if period in (3, 4):
        return "APPRENTICE_PERIODS_3_4"
    if period == 5:
        return "APPRENTICE_PERIOD_5"
    return None


def ratio_limit_resolution(project, worker, as_of=None):
    from projects import governing_rate
    row = governing_rate(project.get("jurisdiction_key"),
                         (worker or {}).get("classification"),
                         (worker or {}).get("apprentice_period"), as_of)
    band = ring_band((worker or {}).get("apprentice_period"))
    if row is not None:
        ratio_limit = num(row.get("apprentice_ratio_max"), None)
        wait_ratio_limit = num(row.get("wait_ratio_max"), None)
        if ratio_limit is None:
            ratio_limit = APPRENTICE_TIER_DEFAULT.get(band, 1.0)
        if wait_ratio_limit is None:
            wait_ratio_limit = WAIT_TIER_DEFAULT.get(band, 1.0)
    else:
        ratio_limit = APPRENTICE_TIER_DEFAULT.get(band, 1.0)
        wait_ratio_limit = WAIT_TIER_DEFAULT.get(band, 1.0)
    ratio_limit = rhu(ratio_limit, 2)
    wait_ratio_limit = rhu(wait_ratio_limit, 2)
    return ratio_limit, wait_ratio_limit


# --------------------------------------------------------------------------
# apprentice_upgrade_projection
# --------------------------------------------------------------------------

def apprentice_upgrade_projection(worker):
    raw = sum(num(day.get("credited_hours"), 0.0)
              for day in DB.all("crew_days")
              if day.get("worker_id") == worker["id"] and day.get("accepted_for_credit"))
    worker["journey_ring_claim_hours"] = rhu(raw, 2)
    worker["upgrade_eligible"] = worker["journey_ring_claim_hours"] > APPLICABLE_CONTRACT_HOURS
    worker["credited_field_hours"] = rhu(sum(
        num(day.get("credited_hours"), 0.0) for day in DB.all("crew_days")
        if day.get("worker_id") == worker["id"] and day.get("accepted_for_credit")), 2)
    return worker["journey_ring_claim_hours"]


# --------------------------------------------------------------------------
# productivity_actuals
# --------------------------------------------------------------------------

def productivity_actuals(project):
    earned = sum(component_crafted_hours(c) for c in project_components(project["id"])
                 if c.get("install_status") == "SET")
    actual = 0.0
    for day in DB.all("crew_days"):
        if day.get("project_id") != project["id"]:
            continue
        if not day.get("accepted_for_credit"):
            continue
        activity = DB.find("trade_activities", day.get("trade_activity_id"))
        if activity is not None and activity.get("status") == "COMPLETE":
            actual += num(day.get("credited_hours"), 0.0)
    return rhu(earned / actual, 4) if actual > 0 else 0.0


# --------------------------------------------------------------------------
# revision_cost_impact
# --------------------------------------------------------------------------

def revision_engineering_hours(revision):
    qualified = num(revision.get("impact_qualified_hours"), 0.0)
    quantity = num(revision.get("revision_quantity"), 0.0)
    return rhu(qualified * quantity / float(REVISION_SCOPE_DIVISOR), 2)


def revision_cost_impact(revision):
    hours = revision_engineering_hours(revision)
    kludge = num(revision.get("kludge_rate_per_hour_cents"), KLUDGE_RATE_PER_HOUR_CENTS)
    negotiated = num(revision.get("negotiated_rate_per_hour_cents"), NEGOTIATED_RATE_PER_HOUR_CENTS)
    markup = revision.get("submitted_markup_pct")
    markup = SUBMITTED_MARKUP_PCT if markup is None else num(markup, SUBMITTED_MARKUP_PCT)
    direct = num(revision.get("direct_shop_cost_cents"), 0.0)
    rework_value = min(hours * kludge, direct)
    negotiated_value = rhu(hours * negotiated * (1 + markup), 0)
    revision["engineering_hours"] = hours
    values = []
    for key in (revision.get("impact_keys") or []):
        values.append({
            "impact_key": key,
            "rework_value_cents": rework_value,
            "negotiated_value_cents": negotiated_value,
        })
    revision["impact_values"] = values
    if revision.get("status") == "APPROVED":
        revision["approved_change_value_cents"] = int(sum(v["negotiated_value_cents"] for v in values))
    else:
        revision["approved_change_value_cents"] = 0
    return values


# --------------------------------------------------------------------------
# Revision flow hours and equipment delta
# --------------------------------------------------------------------------

def revision_flow_hours(revision, project):
    base = (num(revision.get("maintenance_hours"), 0.0)
            + num(revision.get("buffer_before_hours"), 0.0)
            + num(revision.get("momentum_before_hours"), 0.0)
            + num(revision.get("base_service_hours"), 0.0))
    peak = 2.0 if (project or {}).get("safety_program_required") else 1.0
    revision["base_flow_hours"] = rhu(base, 2)
    revision["peak_multiplier"] = peak
    revision["adjusted_flow_hours"] = rhu(base * peak, 2)
    return revision["adjusted_flow_hours"]


def revision_equipment_delta(revision):
    value = num(revision.get("shop_parts_value_cents"), 0.0)
    quantity = num(revision.get("shop_parts_quantity"), 0.0)
    revision["equipment_value_delta_cents"] = rhu(value - quantity * SHOP_PARTS_BASIS_CENTS, 0)
    return revision["equipment_value_delta_cents"]