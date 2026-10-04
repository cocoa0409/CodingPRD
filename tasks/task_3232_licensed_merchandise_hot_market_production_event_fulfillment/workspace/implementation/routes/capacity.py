"""Print capacity windows endpoints.

Request-shape checks (the highest-precedence rung of the validation ladder),
authentication, role authorization and existence checks all live here; the
workflow rules they delegate to live in the service modules.
"""
from flask import request

import db
from errors import (
    ERR_ALREADY_COMMITTED, ERR_CAPACITY_EXCEEDED, ERR_COUNTERFEIT_OVERCOUNT,
    ERR_DESIGN_NOT_APPROVED, ERR_DESIGN_NOT_FOUND, ERR_EVENT_WINDOW_CLOSED,
    ERR_FORBIDDEN_ROLE, ERR_FULFILLMENT_ORDER_NOT_FOUND, ERR_GUARANTEE_FLOOR_BREACH,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVENTORY_INSUFFICIENT,
    ERR_LICENSOR_MISMATCH, ERR_LICENSOR_NOT_FOUND, ERR_LICENSOR_PROJECT_NOT_FOUND,
    ERR_LISTING_UNVERIFIED, ERR_LOT_EXHAUSTED, ERR_NO_ACCRUED_ROYALTY, ERR_NOT_FOUND,
    ERR_PICK_REMARK_REUSED, ERR_PRINT_QUANTITY_EXCEEDED, ERR_PRINT_TYPECAST_MISMATCH,
    ERR_PRODUCTION_ALREADY_COMMITTED, ERR_PRODUCTION_ORDER_NOT_FOUND,
    ERR_RUSH_COMMITMENT_BREACH, ERR_SEGREGATION_OF_DUTIES, ERR_SETTLEMENT_NOOP,
    ERR_STALE_VERSION, ERR_UNAUTHENTICATED, ERR_UNBALANCED_ALLOCATION, fail)
from response import (authenticate, ok_array, ok_object, paginate, pagination,
                      require_roles)
from routing import (
    CAPACITY_TYPES, CARRIERS, CHANNELS, DECISIONS, DEFAULT_HOURS_TO_OUTCOME,
    DESTROY_MODES, DISTRESS_REASONS, EVENT_OUTCOMES, EVENT_WINDOW_HOURS,
    GARMENT_SKUS, PRINT_TYPES, RETIRE_REASONS, TRIGGER_TYPES,
    api, body, check_licensor_ownership, check_licensor_project, check_segregation,
    get_capacity, get_design, get_layer, get_licensor, get_order, get_report, get_run,
    licensor_projects, optional_string, require_enum, require_field, require_int,
    require_instant, require_number, require_order_version, require_version)
from services import fulfillment, ledger, pricing, production



@api.route("/print-capacity", methods=["POST"])
def create_print_capacity():
    payload = body()
    city_code = require_field(payload, "city_code")
    if not isinstance(city_code, str) or not city_code.strip():
        fail(ERR_INVALID_REQUEST, "field 'city_code' must be a non-empty string")
    print_type = require_enum(payload, "print_type", CAPACITY_TYPES)
    window_start_raw = require_field(payload, "window_start")
    window_end_raw = require_field(payload, "window_end")
    try:
        window_start = db.parse_iso(window_start_raw)
        window_end = db.parse_iso(window_end_raw)
    except Exception:
        fail(ERR_INVALID_REQUEST, "window_start and window_end must be ISO 8601 instants")
    if not window_end > window_start:
        fail(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    capacity_qty = require_int(payload, "capacity_qty", positive=True)
    rush_sla_hours = require_int(payload, "rush_sla_hours", positive=True)

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    window = {
        "city_code": city_code,
        "print_type": print_type,
        "window_start": db.fmt_iso(window_start),
        "window_end": db.fmt_iso(window_end),
        "capacity_qty": capacity_qty,
        "reserved_qty": 0,
        "available_qty": capacity_qty,
        "rush_sla_hours": rush_sla_hours,
    }
    db.init_common(window)
    db.store.print_capacities[window["id"]] = window
    return ok_object(window, 201)


@api.route("/print-capacity/<print_capacity_id>", methods=["GET"])
def read_print_capacity(print_capacity_id):
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator", "ProductionPlanner", "AuditOnly"))
    return ok_object(get_capacity(print_capacity_id))


def _refresh_window(window):
    reserved = sum(int(r.get("quantity", 0) or 0)
                   for r in db.store.print_reservations.values()
                   if r.get("print_capacity_id") == window["id"]
                   and r.get("reservation_state") == "HELD")
    window["reserved_qty"] = reserved
    window["available_qty"] = int(window.get("capacity_qty", 0) or 0) - reserved
    return window


def _next_open_window(window):
    """The reclaim rail: a reservation aimed at a closed window is re-pointed at
    the next window honouring the same city_code and print_type."""
    candidates = [w for w in db.store.print_capacities.values()
                  if w.get("city_code") == window.get("city_code")
                  and w.get("print_type") == window.get("print_type")
                  and w["id"] != window["id"]]
    open_windows = [w for w in candidates
                    if db.parse_iso(w.get("window_end")) > db.now()]
    if not open_windows:
        return None
    open_windows.sort(key=lambda w: (str(w.get("window_start") or ""), str(w.get("id"))))
    return open_windows[0]


@api.route("/print-capacity:reserve", methods=["POST"])
def reserve_capacity():
    payload = body()
    print_capacity_id = require_field(payload, "print_capacity_id")
    quantity = require_int(payload, "quantity", positive=True)
    needed_by = require_instant(payload, "needed_by")
    rush_flag = payload.get("rush_flag", False)
    if rush_flag is not None and not isinstance(rush_flag, bool):
        fail(ERR_INVALID_REQUEST, "field 'rush_flag' must be a boolean")

    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator",))

    window = get_capacity(print_capacity_id)

    if db.parse_iso(window.get("window_end")) <= db.now():
        replacement = _next_open_window(window)
        if replacement is None:
            fail(ERR_RUSH_COMMITMENT_BREACH,
                 "no open window honours the same city_code and print_type")
        window = replacement

    # The window must be able to start at or before needed_by under the rush SLA.
    if int(window.get("rush_sla_hours", 0) or 0) > 0 and needed_by is not None:
        if window.get("window_start") > db.fmt_iso(needed_by):
            fail(ERR_RUSH_COMMITMENT_BREACH,
                 "the capacity window cannot start at or before the reservation's needed_by")

    if quantity > int(window.get("available_qty", 0) or 0):
        fail(ERR_CAPACITY_EXCEEDED,
             "the reservation exceeds the window's remaining available units")

    reservation = {
        "print_capacity_id": window["id"],
        "quantity": int(quantity),
        "rush_flag": bool(rush_flag),
        # The client-supplied instant is echoed exactly as it was sent rather
        # than reformatted, so the round trip is byte-identical.
        "needed_by": str(payload.get("needed_by")),
        "reserved_at": db.stamp(),
        "reservation_state": "HELD",
    }
    db.init_common(reservation)
    db.store.print_reservations[reservation["id"]] = reservation
    _refresh_window(window)
    db.touch(window)
    return ok_object(reservation, 201)


@api.route("/print-capacity/<print_capacity_id>/reservations", methods=["GET"])
def list_reservations(print_capacity_id):
    caller = authenticate()
    require_roles(caller, ("FulfillmentCoordinator", "AuditOnly"))
    get_capacity(print_capacity_id)
    limit, offset = pagination()
    items = db.created_order([r for r in db.store.print_reservations.values()
                              if r.get("print_capacity_id") == print_capacity_id])
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


