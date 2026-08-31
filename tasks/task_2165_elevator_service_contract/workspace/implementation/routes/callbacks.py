from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_car, get_resource,
    check_contract_party, fail, req_id, req_enum, req_bool, opt_int, opt_string,
    req_string, clock_iso, parse_dt, now_clock, require_contract_operational,
    require_car_not_decommissioned, contract_of_car,
    ALL_ROLES, ROLE_ADMIN, ROLE_MANAGER, ROLE_CONTRACTOR, ROLE_DISPATCHER,
    CALLBACK_TYPES,
)
from cascades import take_car_out_of_service, return_car_to_service

bp = Blueprint("callbacks", __name__)


def _callback_context(callback_id):
    callback = get_resource(db.callbacks, callback_id)
    car = db.cars.get(callback["car_id"])
    contract = contract_of_car(car) if car is not None else None
    return callback, car, contract


@bp.route(API_PREFIX + "/callbacks", methods=["POST"])
def create_callback():
    user_id, role = authenticate([ROLE_MANAGER, ROLE_ADMIN])
    body = json_body()
    car_id = req_id(body, "car_id")
    car = get_car(car_id)
    contract = contract_of_car(car)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    callback_type = req_enum(body, "callback_type", CALLBACK_TYPES)
    passengers_trapped = opt_int(body, "passengers_trapped", 0, 0)
    out_of_service = req_bool(body, "out_of_service", True)
    if callback_type == "ENTRAPMENT" and passengers_trapped < 1:
        fail("ERR_VALIDATION",
             "passengers_trapped must be at least 1 for an ENTRAPMENT callback.")

    require_contract_operational(contract)
    require_car_not_decommissioned(car)

    callback = new_entity({
        "car_id": car_id,
        "callback_type": callback_type,
        "passengers_trapped": passengers_trapped,
        "out_of_service": out_of_service,
        "reported_at": clock_iso(),
        "status": "REPORTED",
        "fire_dispatch_requested_at": None,
        "fire_dispatch_incident_number": None,
        "arrived_at": None,
        "cleared_at": None,
        "resolution_note": None,
        "response_minutes": None,
        "sla_minutes": None,
        "sla_breached": False,
    })
    db.callbacks[callback["id"]] = callback

    if out_of_service:
        take_car_out_of_service(car)

    return object_response(serialize(callback), 201)


@bp.route(API_PREFIX + "/callbacks/<callback_id>", methods=["GET"])
def read_callback(callback_id):
    authenticate(ALL_ROLES)
    callback = get_resource(db.callbacks, callback_id)
    return object_response(serialize(callback))


@bp.route(API_PREFIX + "/callbacks", methods=["GET"])
def list_callbacks():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.callbacks)
    rows = filter_equals(rows, "car_id")
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "callback_type")
    return paginate(rows)


@bp.route(API_PREFIX + "/callbacks/<callback_id>/fire-dispatch", methods=["POST"])
def fire_dispatch(callback_id):
    user_id, role = authenticate([ROLE_DISPATCHER])
    callback, car, contract = _callback_context(callback_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    incident_number = req_string(body, "incident_number")

    if callback["status"] != "REPORTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if not (callback["callback_type"] == "ENTRAPMENT"
            or callback.get("passengers_trapped", 0) >= 1):
        fail("ERR_FIRE_DISPATCH_NOT_REQUIRED")

    callback["status"] = "ESCALATED"
    callback["fire_dispatch_requested_at"] = clock_iso()
    callback["fire_dispatch_incident_number"] = incident_number
    touch(callback)
    return object_response(serialize(callback))


@bp.route(API_PREFIX + "/callbacks/<callback_id>/arrive", methods=["POST"])
def arrive(callback_id):
    user_id, role = authenticate([ROLE_CONTRACTOR])
    callback, car, contract = _callback_context(callback_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if callback["status"] not in ("REPORTED", "ESCALATED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if callback["callback_type"] == "ENTRAPMENT" and callback["status"] == "REPORTED":
        fail("ERR_ENTRAPMENT_REQUIRES_FIRE_DISPATCH")

    arrived = now_clock()
    reported = parse_dt(callback["reported_at"])
    response_minutes = int((arrived - reported).total_seconds() // 60)
    if callback["callback_type"] == "ENTRAPMENT":
        sla_minutes = contract["entrapment_response_minutes"]
    else:
        sla_minutes = contract["callback_response_minutes"]

    callback["status"] = "ON_SITE"
    callback["arrived_at"] = clock_iso()
    callback["response_minutes"] = response_minutes
    callback["sla_minutes"] = sla_minutes
    callback["sla_breached"] = response_minutes > sla_minutes
    touch(callback)
    return object_response(serialize(callback))


@bp.route(API_PREFIX + "/callbacks/<callback_id>/clear", methods=["POST"])
def clear(callback_id):
    user_id, role = authenticate([ROLE_CONTRACTOR])
    callback, car, contract = _callback_context(callback_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    resolution_note = opt_string(body, "resolution_note")

    if callback["status"] != "ON_SITE":
        fail("ERR_INVALID_STATE_TRANSITION")

    callback["status"] = "CLEARED"
    callback["cleared_at"] = clock_iso()
    callback["resolution_note"] = resolution_note
    touch(callback)

    if car is not None:
        return_car_to_service(car)

    return object_response(serialize(callback))
