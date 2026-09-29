"""Lift, inspection, service posture and lift staffing endpoints."""
from datetime import timedelta

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import auth, ALL_ROLES, LIFT_OPS_MANAGER, MOUNTAIN_OPS_DIRECTOR
from services import cascade, serialize
from util import dec

bp = Blueprint("lifts", __name__)

LIFT_TYPES = ("SURFACE", "FIXED_GRIP", "DETACHABLE", "GONDOLA")
SERVICE_STATUSES = ("CLOSED", "STANDBY", "OPEN", "WIND_HOLD", "MECH_HOLD")
MECHANICAL_STATUSES = ("INSPECTION_DUE", "INSPECTION_PASSED", "INSPECTION_FAILED")
INSPECTION_RESULTS = ("PASS", "FAIL")
ROLE_SLOTS = ("TOP_OP", "BOTTOM_OP", "MID_LOAD", "LIFTIE_FLOAT")
ASSIGNMENT_STATES = ("ASSIGNED", "RELEASED")
INSPECTION_VALID_HOURS = 24
WIND_HOLD_HYSTERESIS_MPH = dec("5.0")


@bp.route("/lifts", methods=["POST"])
def create_lift():
    auth(LIFT_OPS_MANAGER, MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    season = validate.fk(body, "season_id", db.store.seasons, "ERR_SEASON_NOT_FOUND")
    validate.get_str(body, "season_id")
    code = validate.get_str(body, "lift_code", max_len=32)
    lift_type = validate.get_enum(body, "lift_type", LIFT_TYPES)
    threshold = validate.get_num(body, "wind_hold_threshold_mph", exclusive_minimum=0)
    capacity = validate.get_int(body, "hourly_capacity_pph", minimum=1)
    name = validate.get_str(body, "name", required=False, max_len=120)
    required_ops = validate.get_int(body, "required_operator_count",
                                   required=False, default=2, minimum=1)
    for existing in db.season_lifts(season["id"]):
        if existing["lift_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    cascade.require_season_writable(season)
    row = db.new_row({
        "season_id": season["id"],
        "lift_code": code,
        "name": name,
        "lift_type": lift_type,
        "wind_hold_threshold_mph": threshold,
        "hourly_capacity_pph": capacity,
        "required_operator_count": required_ops,
        "service_status": "CLOSED",
        "mechanical_status": "INSPECTION_DUE",
        "last_inspection_at": None,
        "last_inspection_result": None,
        "inspection_valid_until": None,
        "wind_hold_since": None,
    })
    db.store.lifts[row["id"]] = row
    return response.object_response(serialize.lift(row), 201)


@bp.route("/lifts/<lift_id>", methods=["GET"])
def get_lift(lift_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.lifts, lift_id, "ERR_LIFT_NOT_FOUND")
    return response.object_response(serialize.lift(row), 200)


@bp.route("/lifts", methods=["GET"])
def list_lifts():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.lifts)
    season_id = validate.query_value("season_id")
    service_status = validate.query_value("service_status")
    mechanical_status = validate.query_value("mechanical_status")
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    if service_status:
        rows = [r for r in rows if r["service_status"] == service_status]
    if mechanical_status:
        rows = [r for r in rows if r["mechanical_status"] == mechanical_status]
    return response.list_response(rows, serialize.lift, limit, offset)


@bp.route("/lifts/<lift_id>/inspections", methods=["POST"])
def record_inspection(lift_id):
    auth(LIFT_OPS_MANAGER)
    lift = validate.path_row(db.store.lifts, lift_id, "ERR_LIFT_NOT_FOUND")
    body = validate.body()
    result = validate.get_enum(body, "result", INSPECTION_RESULTS)
    validate.get_str(body, "notes", required=False, max_len=500, allow_blank=True)
    season = db.store.seasons.get(lift["season_id"])
    cascade.require_season_writable(season)
    lift["last_inspection_at"] = db.now()
    lift["last_inspection_result"] = result
    db.mark(lift)
    if result == "PASS":
        lift["mechanical_status"] = "INSPECTION_PASSED"
        lift["inspection_valid_until"] = db.now() + timedelta(hours=INSPECTION_VALID_HOURS)
        if lift["service_status"] == "MECH_HOLD":
            lift["service_status"] = "STANDBY"
            for area in db.areas_by_code(lift["season_id"]):
                if area["serving_lift_id"] == lift["id"]:
                    cascade.regate_held_area(area)
    else:
        lift["mechanical_status"] = "INSPECTION_FAILED"
        lift["inspection_valid_until"] = None
        if lift["service_status"] in ("OPEN", "STANDBY", "WIND_HOLD"):
            cascade.mech_hold_lift(lift)
    cascade.refresh_after_terrain_change(season)
    return response.object_response(serialize.lift(lift), 200)


@bp.route("/lifts/<lift_id>/service-status", methods=["POST"])
def service_status(lift_id):
    auth(LIFT_OPS_MANAGER)
    lift = validate.path_row(db.store.lifts, lift_id, "ERR_LIFT_NOT_FOUND")
    body = validate.body()
    target = validate.get_enum(body, "target_status", SERVICE_STATUSES)
    season = db.store.seasons.get(lift["season_id"])
    cascade.require_season_writable(season)
    current = lift["service_status"]

    # Priority 14: only the declared moves are admissible.
    if target == "STANDBY":
        allowed = current == "CLOSED"
    elif target == "OPEN":
        allowed = current in ("STANDBY", "WIND_HOLD")
    elif target == "CLOSED":
        allowed = current in ("OPEN", "STANDBY", "WIND_HOLD")
    else:
        allowed = False
    if not allowed:
        raise ApiError("ERR_LIFT_STATE_INVALID")

    plan = cascade.active_day_plan(lift["season_id"])
    if target == "OPEN":
        # Priority 16: an active plan is required, and WEATHER_HOLD stays active
        # so that a wind hold can still be released against it.
        if plan is None:
            raise ApiError("ERR_DAY_PLAN_NOT_PUBLISHED")
    if target in ("STANDBY", "OPEN"):
        # Priority 32
        if not cascade.inspection_current(lift):
            raise ApiError("ERR_LIFT_INSPECTION_EXPIRED")
    if target == "OPEN" and current == "WIND_HOLD":
        # Priority 33: five mile per hour hysteresis band.
        release_ceiling = dec(lift["wind_hold_threshold_mph"]) - WIND_HOLD_HYSTERESIS_MPH
        if dec(plan["wind_speed_mph"]) > release_ceiling:
            raise ApiError("ERR_WIND_ABOVE_RELEASE_THRESHOLD")
    if target == "OPEN":
        # Priority 37
        from services import calc
        if calc.staffed_operator_count(lift) < lift["required_operator_count"]:
            raise ApiError("ERR_LIFT_OPERATORS_INSUFFICIENT")

    lift["service_status"] = target
    db.mark(lift)
    if target == "OPEN":
        if current == "WIND_HOLD":
            lift["wind_hold_since"] = None
            for area in db.areas_by_code(lift["season_id"]):
                if area["serving_lift_id"] == lift["id"]:
                    cascade.regate_held_area(area)
        cascade.refresh_after_terrain_change(season, force=True)
    elif target == "CLOSED":
        lift["wind_hold_since"] = None
        cascade.cascade_lift_lost_open(lift)
        cascade.refresh_after_terrain_change(season, force=True)
    return response.object_response(serialize.lift(lift), 200)


@bp.route("/lifts/<lift_id>/staff-assignments", methods=["GET"])
def list_lift_assignments(lift_id):
    auth(*ALL_ROLES)
    lift = validate.path_row(db.store.lifts, lift_id, "ERR_LIFT_NOT_FOUND")
    limit, offset = validate.pagination()
    rows = db.lift_assignments(lift["id"])
    state = validate.query_value("state")
    role_on_lift = validate.query_value("role_on_lift")
    if state:
        rows = [r for r in rows if r["state"] == state]
    if role_on_lift:
        rows = [r for r in rows if r["role_on_lift"] == role_on_lift]
    return response.list_response(rows, serialize.staff_assignment, limit, offset)


@bp.route("/lift-staff-assignments", methods=["POST"])
def create_assignment():
    auth(LIFT_OPS_MANAGER)
    body = validate.body()
    lift = validate.fk(body, "lift_id", db.store.lifts, "ERR_LIFT_NOT_FOUND")
    validate.get_str(body, "lift_id")
    operator_code = validate.get_str(body, "operator_code", max_len=32)
    role_on_lift = validate.get_enum(body, "role_on_lift", ROLE_SLOTS)
    shift_start = validate.get_dt(body, "shift_start")
    shift_end = validate.get_dt(body, "shift_end")
    if shift_start >= shift_end:
        raise ApiError("ERR_WINDOW_INVALID")
    season = db.store.seasons.get(lift["season_id"])
    cascade.require_season_writable(season)
    # Priority 38: one ASSIGNED holder per role slot, LIFTIE_FLOAT excepted.
    if role_on_lift != "LIFTIE_FLOAT":
        for peer in db.lift_assignments(lift["id"]):
            if peer["state"] == "ASSIGNED" and peer["role_on_lift"] == role_on_lift:
                raise ApiError("ERR_LIFT_ROLE_SLOT_CONFLICT")
    # Priority 39: 30 minute turnaround around every other ASSIGNED shift.
    turnaround = timedelta(minutes=30)
    for peer in db.by_seq(list(db.store.staff.values())):
        if peer["state"] != "ASSIGNED" or peer["operator_code"] != operator_code:
            continue
        if (shift_start < peer["shift_end"] + turnaround
                and shift_end + turnaround > peer["shift_start"]):
            raise ApiError("ERR_OPERATOR_DOUBLE_BOOKED")
    row = db.new_row({
        "lift_id": lift["id"],
        "operator_code": operator_code,
        "role_on_lift": role_on_lift,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "state": "ASSIGNED",
        "released_at": None,
    })
    db.store.staff[row["id"]] = row
    db.mark(lift)
    return response.object_response(serialize.staff_assignment(row), 201)


@bp.route("/lift-staff-assignments/<assignment_id>/release", methods=["POST"])
def release_assignment(assignment_id):
    auth(LIFT_OPS_MANAGER)
    row = validate.path_row(db.store.staff, assignment_id,
                            "ERR_STAFF_ASSIGNMENT_NOT_FOUND")
    lift = db.store.lifts.get(row["lift_id"])
    season = db.store.seasons.get(lift["season_id"]) if lift else None
    cascade.require_season_writable(season)
    if row["state"] != "ASSIGNED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    row["state"] = "RELEASED"
    row["released_at"] = db.now()
    db.mark(row)
    db.mark(lift)
    from services import calc
    if (lift["service_status"] == "OPEN"
            and calc.staffed_operator_count(lift) < lift["required_operator_count"]):
        lift["service_status"] = "STANDBY"
        cascade.cascade_lift_lost_open(lift)
        cascade.refresh_after_terrain_change(season, force=True)
    return response.object_response(serialize.staff_assignment(row), 200)
