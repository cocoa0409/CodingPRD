"""Forecast windows and the work-order loop."""

from decimal import Decimal
from fractions import Fraction

from flask import Blueprint, request

import calc
import enums
import svc
from auth import ALL_ROLES, authenticate
from envelope import created, listing, ok
from errors import ApiError
from ladder import find, gate, invalid_state, path_row, ref_row
from store import DB
from validate import F, parse, require_interval

bp = Blueprint("planning", __name__)

WO_STATE_ERROR = "ERR_WORK_ORDER_INVALID_STATE"


def _wo_state(work_order, allowed):
    if work_order["state"] not in allowed:
        raise ApiError(
            WO_STATE_ERROR,
            "The work order is in state %s, which does not permit this transition."
            % work_order["state"],
        )


# --------------------------------------------------------------- weather windows
@bp.post("/weather-windows")
def create_window():
    authenticate(["MaintenancePlanner"])
    vals = parse(
        [
            F("wind_farm_id", "string"),
            F("start_utc", "datetime"),
            F("end_utc", "datetime"),
            F("forecast_wind_speed_ms", "number", minv=0),
            F("forecast_gust_ms", "number", minv=0),
            F("icing_risk", "boolean"),
        ]
    )
    require_interval(vals, "start_utc", "end_utc")
    if vals["forecast_gust_ms"] < vals["forecast_wind_speed_ms"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "forecast_gust_ms must be at least forecast_wind_speed_ms.",
        )
    farm = ref_row("farms", vals["wind_farm_id"])
    for other in DB.all("weather_windows"):
        if other["wind_farm_id"] != farm["id"]:
            continue
        if other["state"] not in ("FORECAST", "CONFIRMED"):
            continue
        if calc.overlaps(
            vals["start_utc"], vals["end_utc"], other["start_utc"], other["end_utc"]
        ):
            raise ApiError(
                "ERR_WEATHER_WINDOW_OVERLAP",
                "The interval overlaps an existing forecast or confirmed window.",
            )
    row = DB.new_row(
        wind_farm_id=farm["id"],
        start_utc=vals["start_utc"],
        end_utc=vals["end_utc"],
        forecast_wind_speed_ms=vals["forecast_wind_speed_ms"],
        forecast_gust_ms=vals["forecast_gust_ms"],
        icing_risk=vals["icing_risk"],
        state="FORECAST",
        active_work_order_count=0,
    )
    DB.insert("weather_windows", row)
    return created(row)


@bp.get("/weather-windows/<row_id>")
def get_window(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("weather_windows", row_id))


@bp.get("/weather-windows")
def list_windows():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("weather_windows"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("state", "state", "enum", enums.WINDOW_STATES),
        ],
    )


@bp.post("/weather-windows/<row_id>/confirm")
def confirm_window(row_id):
    authenticate(["MaintenancePlanner"])
    parse([])
    window = path_row("weather_windows", row_id)
    if window["state"] != "FORECAST":
        invalid_state(
            "Only a FORECAST window may be confirmed; it is %s." % window["state"]
        )
    if not window["end_utc"] > DB.now():
        invalid_state("The window has already lapsed and cannot be confirmed.")
    window["state"] = "CONFIRMED"
    DB.touch(window)
    return ok(window)


# ------------------------------------------------------------------ work orders
@bp.post("/work-orders")
def create_work_order():
    authenticate(["MaintenancePlanner", "ReliabilityEngineer"])
    vals = parse(
        [
            F("turbine_id", "string"),
            F("work_type", "enum", members=enums.WORK_TYPES),
            F("required_certification", "enum", members=enums.CERTIFICATIONS),
            F("estimated_hours", "number", gt=0),
            F("fault_event_id", "string", required=False),
            F("blade_damage_id", "string", required=False),
            F("parent_work_order_id", "string", required=False),
        ]
    )
    work_type = vals["work_type"]
    has_fault = "fault_event_id" in vals
    has_blade = "blade_damage_id" in vals
    if work_type == "FAULT_DISPATCH":
        if not has_fault:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "fault_event_id is required for a FAULT_DISPATCH work order.",
            )
    elif has_fault:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "fault_event_id is only accepted on a FAULT_DISPATCH work order.",
        )
    if work_type == "BLADE_REPAIR":
        if not has_blade:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "blade_damage_id is required for a BLADE_REPAIR work order.",
            )
    elif has_blade:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "blade_damage_id is only accepted on a BLADE_REPAIR work order.",
        )

    turbine = ref_row("turbines", vals["turbine_id"])
    event = ref_row("fault_events", vals.get("fault_event_id"))
    damage = ref_row("blade_damages", vals.get("blade_damage_id"))
    parent = ref_row("work_orders", vals.get("parent_work_order_id"))

    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    if event is not None and event["triage_state"] != "DISPATCH_REQUIRED":
        invalid_state(
            "The fault event must be in DISPATCH_REQUIRED; it is %s."
            % event["triage_state"]
        )
    if damage is not None and damage["state"] != "PRIORITIZED":
        invalid_state(
            "The blade finding must be in PRIORITIZED; it is %s." % damage["state"]
        )
    if work_type == "SCHEDULED_SERVICE":
        earliest = Decimal(turbine["service_due_operating_hours"]) - calc.PRE_SERVICE_WINDOW_HOURS
        gate(
            Decimal(turbine["operating_hours"]) < earliest,
            "ERR_SERVICE_NOT_DUE",
            "The turbine is not yet inside its pre-service window.",
        )

    row = DB.new_row(
        turbine_id=turbine["id"],
        fault_event_id=event["id"] if event is not None else None,
        blade_damage_id=damage["id"] if damage is not None else None,
        parent_work_order_id=parent["id"] if parent is not None else None,
        crew_id=None,
        weather_window_id=None,
        work_type=work_type,
        required_certification=vals["required_certification"],
        estimated_hours=vals["estimated_hours"],
        actual_hours=None,
        state="DRAFT",
        revision_round=0,
        submitted_by_user_id=None,
        planned_start_utc=None,
        planned_end_utc=None,
        priority_score=Decimal("0"),
        labor_cost_cents=0,
    )
    DB.insert("work_orders", row)
    if event is not None:
        event["triage_state"] = "DISPATCHED"
        DB.touch(event)
    return created(row)


@bp.get("/work-orders/<row_id>")
def get_work_order(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("work_orders", row_id))


@bp.get("/work-orders")
def list_work_orders():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("work_orders"),
        request.args,
        [
            ("turbine_id", "turbine_id", "string", None),
            ("fault_event_id", "fault_event_id", "string", None),
            ("blade_damage_id", "blade_damage_id", "string", None),
            ("parent_work_order_id", "parent_work_order_id", "string", None),
            ("crew_id", "crew_id", "string", None),
            ("weather_window_id", "weather_window_id", "string", None),
            ("state", "state", "enum", enums.WORK_ORDER_STATES),
            ("work_type", "work_type", "enum", enums.WORK_TYPES),
        ],
    )


@bp.post("/work-orders/<row_id>/submit")
def submit_work_order(row_id):
    user_id, _role = authenticate(["MaintenancePlanner", "ReliabilityEngineer"])
    parse([])
    work_order = path_row("work_orders", row_id)
    _wo_state(work_order, ("DRAFT", "REVISION_REQUESTED"))
    turbine = DB.get("turbines", work_order["turbine_id"])
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    work_order["state"] = "SUBMITTED"
    work_order["submitted_by_user_id"] = user_id
    work_order["priority_score"] = svc.compute_priority_score(work_order)
    DB.touch(work_order)
    return ok(work_order)


@bp.post("/work-orders/<row_id>/request-revision")
def request_revision(row_id):
    authenticate(["ReliabilityEngineer"])
    parse([F("revision_note", "string", minlen=1, nonblank=True)])
    work_order = path_row("work_orders", row_id)
    _wo_state(work_order, ("SUBMITTED", "SCHEDULED"))
    gate(
        int(work_order["revision_round"]) >= calc.MAX_REVISION_ROUNDS,
        "ERR_REVISION_LIMIT_EXCEEDED",
        "The work order has exhausted its revision rounds.",
    )
    was_scheduled = work_order["state"] == "SCHEDULED"
    window = DB.get("weather_windows", work_order["weather_window_id"])
    crew = DB.get("crews", work_order["crew_id"])

    work_order["state"] = "REVISION_REQUESTED"
    work_order["revision_round"] = int(work_order["revision_round"]) + 1
    if was_scheduled:
        work_order["crew_id"] = None
        work_order["weather_window_id"] = None
        work_order["planned_start_utc"] = None
        work_order["planned_end_utc"] = None
    DB.touch(work_order)

    if was_scheduled:
        svc.decrement_window(window, allow_expire=False)
        svc.release_crew(crew)
        if work_order["work_type"] == "BLADE_REPAIR":
            damage = DB.get("blade_damages", work_order["blade_damage_id"])
            if damage is not None and damage["state"] == "REPAIR_SCHEDULED":
                damage["state"] = "PRIORITIZED"
                DB.touch(damage)
    return ok(work_order)


@bp.post("/work-orders/<row_id>/schedule")
def schedule_work_order(row_id):
    authenticate(["MaintenancePlanner"])
    vals = parse(
        [
            F("crew_id", "string"),
            F("weather_window_id", "string"),
            F("planned_start_utc", "datetime"),
            F("planned_end_utc", "datetime"),
        ]
    )
    require_interval(vals, "planned_start_utc", "planned_end_utc")
    work_order = path_row("work_orders", row_id)
    crew = ref_row("crews", vals["crew_id"])
    window = ref_row("weather_windows", vals["weather_window_id"])
    _wo_state(work_order, ("SUBMITTED",))

    gate(
        window["state"] != "CONFIRMED",
        "ERR_WEATHER_WINDOW_NOT_CONFIRMED",
        "The named weather window is %s, not CONFIRMED." % window["state"],
    )
    gate(
        Decimal(crew["max_work_wind_speed_ms"])
        < Decimal(window["forecast_wind_speed_ms"]),
        "ERR_CREW_WIND_LIMIT_EXCEEDED",
        "The crew's wind limit is below the window's forecast wind speed.",
    )
    gate(
        work_order["required_certification"] not in crew["certifications"],
        "ERR_CREW_CERTIFICATION_MISSING",
        "The crew does not hold %s." % work_order["required_certification"],
    )
    if crew["status"] == "OFF_ROTATION":
        invalid_state("The crew is OFF_ROTATION and cannot be scheduled.")

    start = vals["planned_start_utc"]
    end = vals["planned_end_utc"]
    for other in svc.work_orders_of_crew(crew["id"]):
        if other["id"] == work_order["id"]:
            continue
        if other["planned_start_utc"] is None or other["planned_end_utc"] is None:
            continue
        if calc.overlaps(
            start, end, other["planned_start_utc"], other["planned_end_utc"]
        ):
            raise ApiError(
                "ERR_CREW_WINDOW_CONFLICT",
                "The crew already holds an order overlapping this interval.",
            )
    gate(
        not (start >= window["start_utc"] and end <= window["end_utc"]),
        "ERR_WORK_ORDER_OUTSIDE_WINDOW",
        "The planned interval is not contained in the weather window.",
    )

    turbine = DB.get("turbines", work_order["turbine_id"])
    gate(
        crew["wind_farm_id"] != turbine["wind_farm_id"]
        or window["wind_farm_id"] != turbine["wind_farm_id"],
        "ERR_CREW_FARM_MISMATCH",
        "The crew and the window must belong to the turbine's farm.",
    )

    target_date = start.date()
    committed = Decimal(0)
    for other in svc.work_orders_of_crew(crew["id"]):
        if other["id"] == work_order["id"]:
            continue
        if other["planned_start_utc"] is None:
            continue
        if other["planned_start_utc"].date() == target_date:
            committed += Decimal(other["estimated_hours"])
    gate(
        committed + Decimal(work_order["estimated_hours"])
        > Decimal(crew["daily_hours_capacity"]),
        "ERR_CREW_CAPACITY_EXCEEDED",
        "The crew's daily hours capacity would be exceeded.",
    )

    work_order["state"] = "SCHEDULED"
    work_order["crew_id"] = crew["id"]
    work_order["weather_window_id"] = window["id"]
    work_order["planned_start_utc"] = start
    work_order["planned_end_utc"] = end
    DB.touch(work_order)

    window["active_work_order_count"] = int(window["active_work_order_count"]) + 1
    DB.touch(window)
    crew["status"] = "ON_SHIFT"
    DB.touch(crew)
    if work_order["work_type"] == "BLADE_REPAIR":
        damage = DB.get("blade_damages", work_order["blade_damage_id"])
        if damage is not None and damage["state"] == "PRIORITIZED":
            damage["state"] = "REPAIR_SCHEDULED"
            DB.touch(damage)
    return ok(work_order)


DOWN_STATE_FOR = {
    "FAULT_DISPATCH": "DOWN_DISPATCH",
    "SCHEDULED_SERVICE": "DOWN_SERVICE",
    "BLADE_REPAIR": "DOWN_SERVICE",
    "MAJOR_COMPONENT": "DOWN_MAJOR",
}
FROM_STATE_FOR = {
    "FAULT_DISPATCH": "FAULTED",
    "SCHEDULED_SERVICE": "ONLINE",
    "BLADE_REPAIR": "ONLINE",
    "MAJOR_COMPONENT": "ONLINE",
}


@bp.post("/work-orders/<row_id>/start")
def start_work_order(row_id):
    user_id, role = authenticate(["CrewLead", "ReliabilityEngineer"])
    candidate = find("work_orders", row_id)
    if candidate is not None and role == "CrewLead" and candidate["crew_id"] != user_id:
        raise ApiError(
            "ERR_CREW_NOT_ASSIGNED",
            "The acting crew is not the crew assigned to this work order.",
        )
    parse([])
    work_order = path_row("work_orders", row_id)
    _wo_state(work_order, ("SCHEDULED",))
    turbine = DB.get("turbines", work_order["turbine_id"])
    gate(
        turbine["curtailment_state"] == "FORCED_STOP",
        "ERR_TURBINE_FORCE_STOPPED",
        "Work may not be started on a force-stopped turbine.",
    )
    work_type = work_order["work_type"]
    if turbine["availability_state"] != FROM_STATE_FOR[work_type]:
        invalid_state(
            "A %s order requires the turbine in %s; it is %s."
            % (work_type, FROM_STATE_FOR[work_type], turbine["availability_state"])
        )

    work_order["state"] = "IN_PROGRESS"
    DB.touch(work_order)
    turbine["availability_state"] = DOWN_STATE_FOR[work_type]
    DB.touch(turbine)

    window = DB.get("weather_windows", work_order["weather_window_id"])
    if window is not None and window["state"] == "CONFIRMED":
        window["state"] = "CONSUMED"
        DB.touch(window)
    crew = DB.get("crews", work_order["crew_id"])
    if crew is not None:
        DB.apply(crew, {"status": "ON_SHIFT"})
    return ok(work_order)


@bp.post("/work-orders/<row_id>/complete")
def complete_work_order(row_id):
    user_id, role = authenticate(["ReliabilityEngineer", "CrewLead"])
    candidate = find("work_orders", row_id)
    if candidate is not None:
        if (
            candidate["submitted_by_user_id"] is not None
            and candidate["submitted_by_user_id"] == user_id
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The user who submitted the work order may not complete it.",
            )
        if role == "CrewLead" and candidate["crew_id"] != user_id:
            raise ApiError(
                "ERR_CREW_NOT_ASSIGNED",
                "The acting crew is not the crew assigned to this work order.",
            )
    vals = parse([F("actual_hours", "number", required=False, gt=0)])
    work_order = path_row("work_orders", row_id)
    _wo_state(work_order, ("IN_PROGRESS",))

    turbine = DB.get("turbines", work_order["turbine_id"])
    farm = svc.farm_of_turbine(turbine)
    crew = DB.get("crews", work_order["crew_id"])
    window = DB.get("weather_windows", work_order["weather_window_id"])
    work_type = work_order["work_type"]

    # hop 1
    actual_hours = vals.get("actual_hours")
    labor_cost = 0
    if actual_hours is not None and crew is not None:
        labor_cost = calc.rhu_cents(
            Fraction(Decimal(actual_hours)) * Fraction(int(crew["hourly_rate_cents"]))
        )
    work_order["state"] = "COMPLETED"
    if actual_hours is not None:
        work_order["actual_hours"] = actual_hours
    work_order["labor_cost_cents"] = labor_cost
    DB.touch(work_order)

    # hop 2
    if turbine["availability_state"] in ("DOWN_DISPATCH", "DOWN_SERVICE", "DOWN_MAJOR"):
        turbine["availability_state"] = "ONLINE"
    if work_type == "FAULT_DISPATCH":
        turbine["active_fault_code"] = None
    if work_type == "SCHEDULED_SERVICE":
        turbine["last_service_operating_hours"] = Decimal(turbine["operating_hours"])
        svc.recompute_service_figures(turbine)

    # hops 3 and 4
    event = DB.get("fault_events", work_order["fault_event_id"])
    if work_type == "FAULT_DISPATCH" and event is not None:
        if event["triage_state"] == "DISPATCHED":
            event["cleared_at"] = DB.now()
            svc.apply_event_closure(event, turbine)
            DB.touch(event)
    DB.touch(turbine)

    # hops 5 and 6
    svc.downtime_changed(farm["id"], exclude_wo_id=work_order["id"])

    # farm ledger
    svc.post_maintenance_spend(farm, labor_cost)

    # reservations
    svc.decrement_window(window, allow_expire=True)
    svc.release_crew(crew)

    if work_type == "MAJOR_COMPONENT":
        for rep in svc.replacements_of_order(work_order["id"]):
            if rep["state"] == "EXECUTED":
                rep["state"] = "CLOSED"
                DB.touch(rep)
    if work_type == "BLADE_REPAIR":
        damage = DB.get("blade_damages", work_order["blade_damage_id"])
        if damage is not None and damage["state"] == "REPAIR_SCHEDULED":
            damage["state"] = "REPAIRED"
            DB.touch(damage)
    return ok(work_order)


@bp.post("/work-orders/<row_id>/cancel")
def cancel_work_order(row_id):
    authenticate(["MaintenancePlanner", "SiteAdmin"])
    parse([F("cancellation_reason", "string", minlen=1, nonblank=True)])
    work_order = path_row("work_orders", row_id)
    _wo_state(work_order, ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "SCHEDULED"))

    was_scheduled = work_order["state"] == "SCHEDULED"
    window = DB.get("weather_windows", work_order["weather_window_id"])
    crew = DB.get("crews", work_order["crew_id"])

    work_order["state"] = "CANCELLED"
    if was_scheduled:
        work_order["crew_id"] = None
    DB.touch(work_order)

    if was_scheduled:
        svc.decrement_window(window, allow_expire=True)
        svc.release_crew(crew)

    for rep in svc.replacements_of_order(work_order["id"]):
        if rep["state"] in ("PLANNED", "CRANE_RESERVED", "UPTOWER_READY"):
            svc.cancel_replacement(rep)

    event = DB.get("fault_events", work_order["fault_event_id"])
    if event is not None and event["triage_state"] == "DISPATCHED":
        event["triage_state"] = "DISPATCH_REQUIRED"
        DB.touch(event)
    damage = DB.get("blade_damages", work_order["blade_damage_id"])
    if damage is not None and damage["state"] == "REPAIR_SCHEDULED":
        damage["state"] = "PRIORITIZED"
        DB.touch(damage)
    return ok(work_order)
