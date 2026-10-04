"""Service visit endpoints (PRD section 3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_ownership, body, req_field, as_str,
                  as_int, as_enum, parse_dt, find, ok, ok_list)

bp = Blueprint("visits", __name__)

_VISIT_READ_ROLES = {"PlatformAdmin", "FleetManager", "ServiceDispatcher",
                     "ServiceTechnician"}


def _stocking_center_id(visit):
    if visit["service_center_id"] is not None:
        return visit["service_center_id"]
    return DB.vans[visit["mobile_van_id"]]["service_center_id"]


def _restock(row):
    row["restock_needed"] = row["on_hand_qty"] < row["reorder_threshold"]


@bp.post("/evfleet/service-visits")
def create_service_visit():
    uid, role = auth()
    require_role(role, {"FleetManager"})
    b = body()
    vehicle_id = as_str(req_field(b, "vehicle_id"), "vehicle_id")
    # priority 3: existence — vehicle, then any supplied destination FK
    vehicle = find(DB.vehicles, vehicle_id, "vehicle")
    sc_id = b.get("service_center_id")
    mv_id = b.get("mobile_van_id")
    if sc_id is not None:
        as_str(sc_id, "service_center_id")
        find(DB.centers, sc_id, "service center")
    if mv_id is not None:
        as_str(mv_id, "mobile_van_id")
        find(DB.vans, mv_id, "mobile van")
    # priority 4: ownership follows the visited vehicle's order
    order = DB.orders[vehicle["vehicle_order_id"]]
    check_ownership(uid, order["fleet_customer_id"])
    ws_raw = as_str(req_field(b, "window_start"), "window_start")
    we_raw = as_str(req_field(b, "window_end"), "window_end")
    ws = parse_dt(ws_raw, "window_start")
    we = parse_dt(we_raw, "window_end")
    # priority 9: half-open window, end strictly after start
    if not (we > ws):
        raise ApiError(E.ERR_WINDOW_INVALID, 400,
                       "window_end must be strictly after window_start")
    # priority 10: shape — exactly one destination, valid purpose, valid lines
    if (sc_id is None) == (mv_id is None):
        raise ApiError(E.ERR_VALIDATION, 400,
                       "exactly one of service_center_id / mobile_van_id must be set")
    purpose = as_enum(req_field(b, "purpose"),
                      {"MAINTENANCE", "REPAIR", "RECALL"}, "purpose")
    raw_lines = req_field(b, "parts_lines")
    if not isinstance(raw_lines, list):
        raise ApiError(E.ERR_VALIDATION, 400, "parts_lines must be a list")
    lines = []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            raise ApiError(E.ERR_VALIDATION, 400, "each parts line must be an object")
        sku = as_str(req_field(ln, "sku"), "sku")
        qty = as_int(req_field(ln, "qty"), "qty")
        if qty <= 0:
            raise ApiError(E.ERR_VALIDATION, 400, "parts line qty must be > 0")
        lines.append({"sku": sku, "qty": qty})
    # priority 11: same-van travel-buffer separation
    if mv_id is not None:
        buf = timedelta(minutes=calc.VAN_TRAVEL_BUFFER_MINUTES)
        for other in DB.visits.values():
            if other["mobile_van_id"] != mv_id:
                continue
            if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            if not (we <= other["_w_start"] - buf or ws >= other["_w_end"] + buf):
                raise ApiError(E.ERR_VAN_SCHEDULE_CONFLICT, 409,
                               "mobile visit violates the 45-minute travel-buffer "
                               "separation rule")
    # priority 13: vehicle must be COMMISSIONED
    if vehicle["delivery_status"] != "COMMISSIONED":
        raise ApiError(E.ERR_VEHICLE_NOT_IN_SERVICE, 409,
                       "service visits require a COMMISSIONED vehicle")
    # priority 14: parts availability at the stocking center (checked atomically)
    center_id = sc_id if sc_id is not None else DB.vans[mv_id]["service_center_id"]
    for ln in lines:
        row = DB.parts.get((center_id, ln["sku"]))
        available = 0 if row is None else row["on_hand_qty"] - row["reserved_qty"]
        if available < ln["qty"]:
            raise ApiError(E.ERR_PARTS_INSUFFICIENT, 409,
                           "insufficient stock for sku %s at the stocking center"
                           % ln["sku"])
    visit = {
        "vehicle_id": vehicle_id,
        "service_center_id": sc_id,
        "mobile_van_id": mv_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "purpose": purpose,
        "parts_lines": lines,
        "status": "SCHEDULED",
        "completed_by_user_id": None,
        "_w_start": ws,
        "_w_end": we,
    }
    store.stamp_new(visit)
    DB.visits[visit["id"]] = visit
    # side effect: reserve parts at the stocking center
    for ln in lines:
        row = DB.parts[(center_id, ln["sku"])]
        row["reserved_qty"] += ln["qty"]
        _restock(row)
        store.touch(row)
    return ok(store.public(visit), 201)


@bp.get("/evfleet/service-visits/<vid>")
def get_service_visit(vid):
    _, role = auth()
    require_role(role, _VISIT_READ_ROLES)
    e = find(DB.visits, vid, "service visit")
    return ok(store.public(e), 200)


@bp.get("/evfleet/service-visits")
def list_service_visits():
    _, role = auth()
    require_role(role, _VISIT_READ_ROLES)
    items = list(DB.visits.values())
    vh = request.args.get("vehicle_id")
    if vh is not None:
        items = [v for v in items if v["vehicle_id"] == vh]
    sc = request.args.get("service_center_id")
    if sc is not None:
        items = [v for v in items if v["service_center_id"] == sc]
    mv = request.args.get("mobile_van_id")
    if mv is not None:
        items = [v for v in items if v["mobile_van_id"] == mv]
    return ok_list(items)


_VISIT_ROLE_STATES = {
    "ServiceTechnician": {"IN_PROGRESS", "COMPLETED"},
    "FleetManager": {"CANCELLED"},
}


@bp.post("/evfleet/service-visits/<vid>/transition")
def transition_service_visit(vid):
    uid, role = auth()
    if role not in _VISIT_ROLE_STATES:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s is not permitted for this endpoint" % role)
    b = body()
    to_state = as_str(req_field(b, "to_state"), "to_state")
    if to_state not in _VISIT_ROLE_STATES[role]:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s may not drive to_state %s" % (role, to_state))
    visit = find(DB.visits, vid, "service visit")
    # priority 4: ownership for the FleetManager-driven cancellation
    if role == "FleetManager":
        order = DB.orders[DB.vehicles[visit["vehicle_id"]]["vehicle_order_id"]]
        check_ownership(uid, order["fleet_customer_id"])
    # priority 6: terminal lockdown, then state preconditions
    if visit["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "service visit is in terminal state %s" % visit["status"])
    st = visit["status"]
    if to_state == "IN_PROGRESS":
        if st != "SCHEDULED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "IN_PROGRESS is offered from SCHEDULED")
    elif to_state == "COMPLETED":
        if st != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "COMPLETED is offered from IN_PROGRESS")
    elif to_state == "CANCELLED":
        if st != "SCHEDULED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "cancellation is offered only from SCHEDULED")
    # side effects
    if to_state in ("COMPLETED", "CANCELLED") and visit["parts_lines"]:
        center_id = _stocking_center_id(visit)
        for ln in visit["parts_lines"]:
            row = DB.parts[(center_id, ln["sku"])]
            if to_state == "COMPLETED":
                # reservation converts to consumption; conservation identity holds
                row["reserved_qty"] -= ln["qty"]
                row["on_hand_qty"] -= ln["qty"]
                row["consumed_total_qty"] += ln["qty"]
            else:
                # cancellation releases the reservation only
                row["reserved_qty"] -= ln["qty"]
            _restock(row)
            store.touch(row)
    if to_state == "COMPLETED":
        visit["completed_by_user_id"] = uid
    visit["status"] = to_state
    store.touch(visit)
    return ok(store.public(visit), 200)
