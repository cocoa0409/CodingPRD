"""Derived (computed) fields and the JSON serialisers for every entity."""
from datetime import timedelta
from decimal import Decimal

from core import (dfloor, fmt_dt, hours_between, ordered, parse_dt, rhu, rhu_f, store)

RESERVING_PLAN_STATES = ("CONFIGURED", "PENDING_ENGINEERING", "APPROVED", "RELEASED")
FIELD_ON_SITE = ("MOBILIZED", "LIFTING", "WIND_HOLD", "SECURED")
RIGGER_LADDER = ["NONE", "BASIC", "INTERMEDIATE", "ADVANCED", "MASTER"]
LIFT_CLASS_RANK = {"NOT_CLASSIFIED": 0, "STANDARD": 1, "CRITICAL": 2, "ENGINEERED_CRITICAL": 3}
REQUIRED_RIGGER_LEVEL = {"STANDARD": "BASIC", "CRITICAL": "ADVANCED",
                         "ENGINEERED_CRITICAL": "MASTER", "NOT_CLASSIFIED": "NONE"}


# ------------------------------------------------------------------- crane --
def plans_on_crane(crane_id):
    return [p for p in ordered(store.lift_plans) if p["crane_id"] == crane_id]


def crane_reserving_plans(crane_id):
    return [p for p in plans_on_crane(crane_id) if p["plan_status"] in RESERVING_PLAN_STATES]


def crane_reserved_hours(crane_id):
    total = Decimal(0)
    plans = crane_reserving_plans(crane_id)
    for p in plans:
        total += hours_between(parse_dt(p["window_start"]), parse_dt(p["window_end"]))
    return rhu_f(total, 2), len(plans)


def crane_status(crane):
    expires = parse_dt(crane["annual_inspection_expires_on"])
    if crane["out_of_service_flag"] or (expires is not None and store.now >= expires):
        return "OUT_OF_SERVICE"
    for p in plans_on_crane(crane["id"]):
        if p["field_status"] in FIELD_ON_SITE:
            return "IN_SERVICE"
    hours, _count = crane_reserved_hours(crane["id"])
    if hours > 0:
        return "RESERVED"
    return "AVAILABLE"


# --------------------------------------------------------------- personnel --
def person_status(person):
    expires = parse_dt(person["certification_expires_on"])
    if expires is not None and store.now >= expires:
        return "EXPIRED"
    return "ACTIVE"


def _day_bounds(dt):
    day_open = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_open, day_open + timedelta(days=1)


def operator_day_hours(operator_id, extra_plan=None, exclude_plan_id=None):
    """{day_open_datetime: Decimal hours} across the operator's reserving plans."""
    windows = []
    for p in ordered(store.lift_plans):
        if exclude_plan_id is not None and p["id"] == exclude_plan_id:
            continue
        if p["operator_id"] != operator_id:
            continue
        if p["plan_status"] not in RESERVING_PLAN_STATES:
            continue
        windows.append((parse_dt(p["window_start"]), parse_dt(p["window_end"])))
    if extra_plan is not None:
        windows.append(extra_plan)

    day_hours = {}
    for start, end in windows:
        cursor, _ = _day_bounds(start)
        while cursor < end:
            day_open, day_close = cursor, cursor + timedelta(days=1)
            lo = max(start, day_open)
            hi = min(end, day_close)
            if hi > lo:
                day_hours[day_open] = day_hours.get(day_open, Decimal(0)) + hours_between(lo, hi)
            cursor = day_close
    return day_hours


def person_peak_daily_hours(person):
    if person["role_type"] != "OPERATOR":
        return 0.0
    day_hours = operator_day_hours(person["id"])
    if not day_hours:
        return 0.0
    return rhu_f(max(day_hours.values()), 2)


# -------------------------------------------------------------------- gear --
def gear_status(gear):
    stored = gear["status"]
    if stored == "SERVICEABLE":
        due = parse_dt(gear["next_inspection_due_at"]) if gear["next_inspection_due_at"] else None
        if due is not None and store.now >= due:
            return "DUE_INSPECTION"
    return stored


def gear_committed_count(gear_id):
    return len([a for a in store.gear_assignments.values()
                if a["gear_id"] == gear_id and a["status"] == "ACTIVE"])


def gear_effective_wll(gear):
    multiplier = max(Decimal("1") - Decimal("0.05") * gear["repair_count"], Decimal("0.70"))
    return dfloor(Decimal(gear["rated_wll_lb"]) * multiplier)


# ---------------------------------------------------------------- customer --
def customer_ledger(customer_id):
    open_cents = 0
    count = 0
    for inv in store.invoices.values():
        if inv["customer_id"] != customer_id:
            continue
        count += 1
        if inv["status"] in ("ISSUED", "DISPUTED"):
            open_cents += inv["total_cents"]
    return open_cents, count


def plan_invoice_count(plan_id):
    return len([i for i in store.invoices.values() if i["lift_plan_id"] == plan_id])


def plan_active_assignments(plan_id):
    return [a for a in ordered(store.gear_assignments)
            if a["lift_plan_id"] == plan_id and a["status"] == "ACTIVE"]


# ------------------------------------------------------------ serialisers ---
def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = rec["created_at"]
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def customer_json(c):
    open_cents, count = customer_ledger(c["id"])
    return _common(c, {
        "account_name": c["account_name"],
        "billing_terms": c["billing_terms"],
        "credit_hold": c["credit_hold"],
        "credit_hold_reason": c["credit_hold_reason"],
        "open_receivable_cents": open_cents,
        "invoice_count": count,
    })


def site_json(s):
    return _common(s, {
        "customer_id": s["customer_id"],
        "address_label": s["address_label"],
        "jurisdiction_code": s["jurisdiction_code"],
        "soil_bearing_capacity_psf": s["soil_bearing_capacity_psf"],
        "proximity_to_energized_lines_ft": s["proximity_to_energized_lines_ft"],
        "over_water": s["over_water"],
        "survey_status": s["survey_status"],
        "last_surveyed_at": s["last_surveyed_at"],
        "access_notes": s["access_notes"],
        "mat_inventory_available": s["mat_inventory_available"],
    })


def crane_json(c):
    hours, count = crane_reserved_hours(c["id"])
    return _common(c, {
        "model_code": c["model_code"],
        "class_tons": c["class_tons"],
        "gross_weight_lb": c["gross_weight_lb"],
        "counterweight_lb": c["counterweight_lb"],
        "outrigger_pad_area_sqft": c["outrigger_pad_area_sqft"],
        "max_line_pull_lb": c["max_line_pull_lb"],
        "rated_max_wind_mph": c["rated_max_wind_mph"],
        "annual_inspection_expires_on": c["annual_inspection_expires_on"],
        "mob_demob_cents": c["mob_demob_cents"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "out_of_service_flag": c["out_of_service_flag"],
        "status": crane_status(c),
        "reserved_hours_total": hours,
        "active_plan_count": count,
    })


def chart_json(e):
    return _common(e, {
        "crane_id": e["crane_id"],
        "configuration": e["configuration"],
        "boom_length_ft": e["boom_length_ft"],
        "radius_ft": e["radius_ft"],
        "gross_capacity_lb": e["gross_capacity_lb"],
    })


def personnel_json(p):
    return _common(p, {
        "full_name": p["full_name"],
        "role_type": p["role_type"],
        "certification_number": p["certification_number"],
        "certification_expires_on": p["certification_expires_on"],
        "endorsement_class_tons": p["endorsement_class_tons"],
        "rigger_level": p["rigger_level"],
        "pe_license_state": p["pe_license_state"],
        "status": person_status(p),
        "peak_daily_assigned_hours": person_peak_daily_hours(p),
    })


def gear_json(g):
    return _common(g, {
        "gear_tag": g["gear_tag"],
        "gear_type": g["gear_type"],
        "rated_wll_lb": g["rated_wll_lb"],
        "weight_lb": g["weight_lb"],
        "inspection_interval_days": g["inspection_interval_days"],
        "last_inspection_at": g["last_inspection_at"],
        "next_inspection_due_at": g["next_inspection_due_at"],
        "repair_count": g["repair_count"],
        "effective_wll_lb": g["effective_wll_lb"],
        "status": gear_status(g),
        "committed_assignment_count": gear_committed_count(g["id"]),
    })


def inspection_json(i):
    return _common(i, {
        "gear_id": i["gear_id"],
        "result": i["result"],
        "inspector_note": i["inspector_note"],
        "inspected_at": i["inspected_at"],
        "resulting_status": i["resulting_status"],
        "repair_count_after": i["repair_count_after"],
    })


PLAN_FIELDS = [
    "site_id", "customer_id", "crane_id", "operator_id", "rigger_id", "job_reference",
    "window_start", "window_end", "load_weight_lb", "sail_area_sqft", "personnel_lift",
    "multi_crane", "road_closure_requested", "configuration", "boom_length_ft", "radius_ft",
    "parts_of_line", "block_weight_lb", "jib_weight_lb", "aux_head_weight_lb",
    "chart_gross_capacity_lb", "hoist_line_capacity_lb", "net_capacity_lb", "rigging_weight_lb",
    "total_load_lb", "utilization_pct", "lift_class", "bearing_variant", "per_outrigger_load_lb",
    "bearing_pressure_psf", "matting_required", "mat_area_required_sqft", "mat_count",
    "allowable_wind_mph", "escort_required", "permit_required", "rigging_verified",
    "standby_hours_billable", "plan_status", "field_status", "cancellation_reason",
]


def plan_json(p):
    out = {k: p[k] for k in PLAN_FIELDS}
    out["invoice_count"] = plan_invoice_count(p["id"])
    return _common(p, out)


def assignment_json(a):
    return _common(a, {
        "lift_plan_id": a["lift_plan_id"],
        "gear_id": a["gear_id"],
        "leg_count": a["leg_count"],
        "sling_angle_deg": a["sling_angle_deg"],
        "load_angle_factor": a["load_angle_factor"],
        "leg_tension_lb": a["leg_tension_lb"],
        "effective_wll_lb": a["effective_wll_lb"],
        "status": a["status"],
    })


def review_json(r):
    return _common(r, {
        "lift_plan_id": r["lift_plan_id"],
        "author_personnel_id": r["author_personnel_id"],
        "stamped_by_personnel_id": r["stamped_by_personnel_id"],
        "analysis_notes": r["analysis_notes"],
        "revision_round": r["revision_round"],
        "change_request_note": r["change_request_note"],
        "decision_note": r["decision_note"],
        "final_bearing_pressure_psf": r["final_bearing_pressure_psf"],
        "final_mat_count": r["final_mat_count"],
        "status": r["status"],
    })


def permit_json(p):
    return _common(p, {
        "lift_plan_id": p["lift_plan_id"],
        "permit_type": p["permit_type"],
        "jurisdiction_code": p["jurisdiction_code"],
        "escort_required": p["escort_required"],
        "required_lead_days": p["required_lead_days"],
        "permit_fee_cents": p["permit_fee_cents"],
        "cancellation_fee_cents": p["cancellation_fee_cents"],
        "submitted_at": p["submitted_at"],
        "decision_at": p["decision_at"],
        "agency_reference": p["agency_reference"],
        "denial_reason": p["denial_reason"],
        "status": p["status"],
    })


def standby_json(s):
    return _common(s, {
        "lift_plan_id": s["lift_plan_id"],
        "cause": s["cause"],
        "wind_speed_mph": s["wind_speed_mph"],
        "started_at": s["started_at"],
        "ended_at": s["ended_at"],
        "raw_duration_hours": s["raw_duration_hours"],
        "forced_wind_hold": s["forced_wind_hold"],
        "status": s["status"],
    })


INVOICE_FIELDS = [
    "lift_plan_id", "customer_id", "billing_mode", "on_site_hours", "travel_hours",
    "travel_miles", "lump_sum_cents", "standby_hours_source", "billable_hours",
    "regular_hours", "overtime_hours", "line_regular_cents", "line_overtime_cents",
    "line_standby_cents", "line_travel_cents", "line_mobdemob_cents", "line_lump_sum_cents",
    "line_permit_cancellation_cents", "subtotal_cents", "discount_pct", "discount_cents",
    "fuel_surcharge_cents", "total_cents", "system_generated", "status",
]


def invoice_json(i):
    return _common(i, {k: i[k] for k in INVOICE_FIELDS})
