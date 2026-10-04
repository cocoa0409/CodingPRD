"""Stall, check-in, and EquipmentFault endpoints (PRD 3.3, 3.9)."""
from db import db, now
from errors import not_found, raise_error, invalid_request
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
    get_bool,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import stall as ser_stall, order as ser_order, equipment_fault as ser_fault
from services import (
    make_record,
    touch,
    get_location,
    get_stall_nested,
    get_fault_nested,
    recompute_location_posture,
    cancel_order,
)
from . import stalls_bp

STALL_KINDS = ["STALL", "PATIO"]
STALL_STATUSES = ["IDLE", "OCCUPIED", "OUT_OF_SERVICE"]
FAULT_KINDS = ["INTERCOM_DEAD", "PAYMENT_TERMINAL_DEAD", "MENU_BOARD_DEAD"]
FAULT_REPORTER_ROLES = ["CARHOP", "SHIFT_MANAGER"]
STALL_READ_ROLES = ["ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin", "Customer"]
FAULT_READ_ROLES = ["Carhop", "ShiftManager", "PlatformAdmin"]


@stalls_bp.route("/locations/<locationId>/stalls", methods=["POST"])
def create_stall(locationId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    loc = get_location(locationId)
    body = body_json()
    stall_number = get_int(body, "stall_number", required=True)
    kind = get_enum(body, "kind", STALL_KINDS, required=True)
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "stall_number": stall_number,
            "kind": kind,
            "intercom_functional": True,
            "status": "IDLE",
            "current_order_id": None,
        }
    )
    db.stalls[rec["id"]] = rec
    recompute_location_posture(loc, touch_location=False)
    return success_object(ser_stall(rec), 201)


@stalls_bp.route("/locations/<locationId>/stalls", methods=["GET"])
def list_stalls(locationId):
    require_auth(STALL_READ_ROLES)
    from flask import request

    get_location(locationId)
    status = request.args.get("status")
    kind = request.args.get("kind")
    if status is not None and status not in STALL_STATUSES:
        invalid_request("status must be a valid stall status")
    if kind is not None and kind not in STALL_KINDS:
        invalid_request("kind must be STALL or PATIO")
    current_order_id = request.args.get("current_order_id")
    stalls = [s for s in db.stalls.values() if s["location_id"] == locationId]
    if status is not None:
        stalls = [s for s in stalls if s["status"] == status]
    if kind is not None:
        stalls = [s for s in stalls if s["kind"] == kind]
    if current_order_id is not None:
        stalls = [s for s in stalls if s["current_order_id"] == current_order_id]
    stalls = sort_by_created(stalls)
    limit, offset = pagination_params()
    total = len(stalls)
    page = stalls[offset : offset + limit]
    return success_array([ser_stall(s) for s in page], limit, offset, total)


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>", methods=["GET"])
def get_stall(locationId, stallId):
    require_auth(STALL_READ_ROLES)
    loc, st = get_stall_nested(locationId, stallId)
    return success_object(ser_stall(st))


def _create_checkin_order(loc, stall, channel, customer_id):
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "stall_id": stall["id"],
            "customer_id": customer_id,
            "channel": channel,
            "status": "DRAFT",
            "payment_status": "UNPAID",
            "checked_in_at": now(),
            "placed_at": None,
            "ready_at": None,
            "delivered_at": None,
            "service_target_seconds": None,
            "late_flag": False,
            "subtotal_cents": 0,
            "offer_discount_cents": 0,
            "tax_cents": 0,
            "tip_cents": 0,
            "total_cents": 0,
            "total_tendered_cents": 0,
            "delivery_run_id": None,
            "run_position": None,
            "checked_in_rush_index": loc["rush_index"],
        }
    )
    db.orders[rec["id"]] = rec
    stall["status"] = "OCCUPIED"
    stall["current_order_id"] = rec["id"]
    touch(stall)
    # Check-in mutates the stall, not the location row (PRD 3.3).
    recompute_location_posture(loc, touch_location=False)
    return rec


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/checkin", methods=["POST"])
def checkin(locationId, stallId):
    require_auth(["Customer", "ShiftManager"])
    loc, st = get_stall_nested(locationId, stallId)
    body = body_json()
    customer_id = body.get("customer_id")
    if customer_id is not None:
        if not isinstance(customer_id, str):
            invalid_request("customer_id must be a string")
        if customer_id not in db.customers:
            not_found("Customer not found")
    expected = get_int(body, "expected_location_version", required=True)
    if expected != loc["version"]:
        raise_error("ERR_STALE_VERSION", "Stale location version; re-read the location")
    if loc["weather_mode"] == "HEAT_ADVISORY" and st["kind"] == "PATIO":
        raise_error("ERR_STALL_WEATHER_CLOSED", "Patio stalls are closed during a heat advisory")
    if loc["lane_posture"] == "CURBSIDE_ONLY":
        raise_error("ERR_LANE_CLOSED", "Location is curbside-only")
    if st["status"] != "IDLE":
        raise_error("ERR_STALL_OCCUPIED", "Stall is not IDLE")
    channel = "PATIO" if st["kind"] == "PATIO" else "STALL_INTERCOM"
    order = _create_checkin_order(loc, st, channel, customer_id)
    return success_object(ser_order(order), 201)


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/app-checkin", methods=["POST"])
def app_checkin(locationId, stallId):
    require_auth(["Customer"])
    loc, st = get_stall_nested(locationId, stallId)
    body = body_json()
    customer_id = body.get("customer_id")
    if customer_id is not None and not isinstance(customer_id, str):
        invalid_request("customer_id must be a string")
    customer = db.customers.get(customer_id) if customer_id else None
    if customer is None or not customer["app_user"]:
        raise_error("ERR_APP_ONLY", "App check-in requires an existing app-user customer")
    expected = get_int(body, "expected_location_version", required=True)
    if expected != loc["version"]:
        raise_error("ERR_STALE_VERSION", "Stale location version; re-read the location")
    if loc["weather_mode"] == "HEAT_ADVISORY" and st["kind"] == "PATIO":
        raise_error("ERR_STALL_WEATHER_CLOSED", "Patio stalls are closed during a heat advisory")
    if st["status"] != "IDLE":
        raise_error("ERR_STALL_OCCUPIED", "Stall is not IDLE")
    channel = "PATIO" if st["kind"] == "PATIO" else "APP_CHECKIN"
    order = _create_checkin_order(loc, st, channel, customer_id)
    return success_object(ser_order(order), 201)


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/faults", methods=["POST"])
def report_fault(locationId, stallId):
    require_auth(["Carhop", "ShiftManager"])
    loc, st = get_stall_nested(locationId, stallId)
    body = body_json()
    kind = get_enum(body, "kind", FAULT_KINDS, required=True)
    note = get_str(body, "note")
    reported_by = get_enum(body, "reported_by_role", FAULT_REPORTER_ROLES, required=True)
    rec = make_record()
    rec.update(
        {
            "stall_id": st["id"],
            "reported_by_role": reported_by,
            "kind": kind,
            "note": note,
            "status": "OPEN",
        }
    )
    db.equipment_faults[rec["id"]] = rec
    st["intercom_functional"] = False
    if kind == "MENU_BOARD_DEAD":
        st["status"] = "OUT_OF_SERVICE"
        recompute_location_posture(loc, touch_location=False)
    touch(st)
    return success_object(ser_fault(rec), 201)


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/faults", methods=["GET"])
def list_faults(locationId, stallId):
    require_auth(FAULT_READ_ROLES)
    from flask import request

    loc, st = get_stall_nested(locationId, stallId)
    status = request.args.get("status")
    if status is not None and status not in ("OPEN", "RESOLVED"):
        invalid_request("status must be OPEN or RESOLVED")
    faults = [f for f in db.equipment_faults.values() if f["stall_id"] == st["id"]]
    if status is not None:
        faults = [f for f in faults if f["status"] == status]
    faults = sort_by_created(faults)
    limit, offset = pagination_params()
    total = len(faults)
    page = faults[offset : offset + limit]
    return success_array([ser_fault(f) for f in page], limit, offset, total)


@stalls_bp.route(
    "/locations/<locationId>/stalls/<stallId>/faults/<faultId>/resolve", methods=["POST"]
)
def resolve_fault(locationId, stallId, faultId):
    require_auth(["ShiftManager"])
    loc, st, fault = get_fault_nested(locationId, stallId, faultId)
    if fault["status"] != "OPEN":
        from errors import invalid_state

        invalid_state("Fault is not OPEN")
    fault["status"] = "RESOLVED"
    touch(fault)
    any_open = any(
        f["stall_id"] == st["id"] and f["status"] == "OPEN"
        for f in db.equipment_faults.values()
    )
    if not any_open:
        st["intercom_functional"] = True
        touch(st)
    return success_object(ser_fault(fault))


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/set_out_of_service", methods=["POST"])
def set_out_of_service(locationId, stallId):
    require_auth(["ShiftManager"])
    loc, st = get_stall_nested(locationId, stallId)
    body = body_json()
    force_cancel = get_bool(body, "force_cancel", default=False)
    if st["status"] == "OUT_OF_SERVICE":
        from errors import invalid_state

        invalid_state("Stall is already OUT_OF_SERVICE")
    if st["status"] == "OCCUPIED":
        if not force_cancel:
            raise_error("ERR_STALL_OCCUPIED", "Stall is occupied; force_cancel is required")
        order = db.orders.get(st["current_order_id"])
        if order is not None and order["status"] not in ("CANCELLED", "DELIVERED"):
            cancel_order(order)
    st["status"] = "OUT_OF_SERVICE"
    touch(st)
    recompute_location_posture(loc, touch_location=False)
    return success_object(ser_stall(st))


@stalls_bp.route("/locations/<locationId>/stalls/<stallId>/return_to_service", methods=["POST"])
def return_to_service(locationId, stallId):
    require_auth(["ShiftManager"])
    loc, st = get_stall_nested(locationId, stallId)
    if st["status"] != "OUT_OF_SERVICE":
        from errors import invalid_state

        invalid_state("Stall is not OUT_OF_SERVICE")
    any_open = any(
        f["stall_id"] == st["id"] and f["status"] == "OPEN"
        for f in db.equipment_faults.values()
    )
    if any_open:
        raise_error("ERR_FAULT_STILL_OPEN", "An OPEN equipment fault remains on the stall")
    st["status"] = "IDLE"
    st["intercom_functional"] = True
    touch(st)
    recompute_location_posture(loc, touch_location=False)
    return success_object(ser_stall(st))
