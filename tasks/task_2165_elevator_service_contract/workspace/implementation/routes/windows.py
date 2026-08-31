from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_car, get_resource,
    check_contract_party, fail, req_id, opt_id, req_enum, req_datetime,
    require_car_not_decommissioned, require_car_not_red_tagged, contract_of_car,
    now_clock, parse_dt,
    ALL_ROLES, ROLE_ADMIN, ROLE_CONTRACTOR, WINDOW_TYPES,
)
from calc import (
    rule1_conflict, rule2_conflict, recompute_scheduled_downtime,
    recompute_window_count,
)

bp = Blueprint("windows", __name__)


@bp.route(API_PREFIX + "/downtime-windows", methods=["POST"])
def create_window():
    user_id, role = authenticate([ROLE_ADMIN, ROLE_CONTRACTOR])
    body = json_body()

    car_id = req_id(body, "car_id")
    car = get_car(car_id)
    project_id = opt_id(body, "project_id")
    project = None
    if project_id is not None:
        project = get_resource(db.projects, project_id)

    contract = contract_of_car(car)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    window_type = req_enum(body, "window_type", WINDOW_TYPES)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        fail("ERR_VALIDATION", "window_end must be strictly after window_start.")

    # §3.1: reserving a downtime window requires the contract to be ACTIVE.
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")

    require_car_not_decommissioned(car)
    require_car_not_red_tagged(car)

    if rule1_conflict(car_id, window_start, window_end, window_type):
        fail("ERR_DOWNTIME_WINDOW_CONFLICT")
    if window_type == "MODERNIZATION" and rule2_conflict(car, window_start, window_end):
        fail("ERR_CONTRACT_MODERNIZATION_CAPACITY")

    duration_minutes = int((window_end - window_start).total_seconds() // 60)

    window = new_entity({
        "car_id": car_id,
        "project_id": project_id,
        "window_type": window_type,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "duration_minutes": duration_minutes,
        "status": "SCHEDULED",
        "reschedule_count": 0,
    })
    db.windows[window["id"]] = window

    recompute_scheduled_downtime(car)
    touch(car)

    if project is not None:
        project["window_count"] = project["window_count"] + 1
        touch(project)

    return object_response(serialize(window), 201)


@bp.route(API_PREFIX + "/downtime-windows/<window_id>", methods=["GET"])
def read_window(window_id):
    authenticate(ALL_ROLES)
    window = get_resource(db.windows, window_id)
    return object_response(serialize(window))


@bp.route(API_PREFIX + "/downtime-windows", methods=["GET"])
def list_windows():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.windows)
    rows = filter_equals(rows, "car_id")
    rows = filter_equals(rows, "project_id")
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "window_type")
    return paginate(rows)


@bp.route(API_PREFIX + "/downtime-windows/<window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    user_id, role = authenticate([ROLE_ADMIN, ROLE_CONTRACTOR])
    window = get_resource(db.windows, window_id)
    car = db.cars.get(window["car_id"])
    contract = contract_of_car(car) if car is not None else None
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if window["status"] not in ("SCHEDULED", "RESCHEDULE_REQUIRED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if window["status"] == "SCHEDULED":
        start = parse_dt(window["window_start"])
        if start is not None and now_clock() >= start:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A downtime window that has already begun can no longer be cancelled.")

    window["status"] = "CANCELLED"
    touch(window)

    if car is not None:
        recompute_scheduled_downtime(car)
        touch(car)

    if window.get("project_id"):
        project = db.projects.get(window["project_id"])
        if project is not None:
            project["window_count"] = max(0, project["window_count"] - 1)
            touch(project)

    return object_response(serialize(window))
