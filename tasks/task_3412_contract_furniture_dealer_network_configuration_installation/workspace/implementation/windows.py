# Install windows routes (PRD 3.7; scaffold Tables 2/5).
from flask import Blueprint, request

import authz
import calc
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("windows", __name__)


def _load_window(window_id):
    window = state.windows.get(window_id)
    if window is None:
        errors.not_found("ERR_WINDOW_NOT_FOUND", "No install window with the given id")
    return window


def _window_visible_to(window, role, user_id):
    if role == "ManufacturerAdmin":
        return True
    phase = state.phases.get(window["installation_phase_id"])
    if phase is None:
        return False
    order = state.orders.get(phase["project_order_id"])
    return order is not None and order["dealer_id"] == user_id


@bp.post("/install-windows")
def create_window():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    body = validate.body_json(request)
    # Step 3: body FK resolves.
    phase_id = body.get("installation_phase_id")
    if isinstance(phase_id, str) and phase_id not in state.phases:
        errors.not_found("ERR_PHASE_NOT_FOUND", "No installation phase with the given id")
    phase = state.phases.get(phase_id) if isinstance(phase_id, str) else None
    # Step 4: ownership of the target phase's order.
    if phase is not None:
        authz.check_phase_ownership(phase, role, user_id)
    # Step 5: body shape.
    phase_id = validate.req_str(body, "installation_phase_id")
    start_at = validate.req_datetime(body, "start_at")
    end_at = validate.req_datetime(body, "end_at")
    union_required = validate.req_bool(body, "union_required")
    elevator_required = validate.req_bool(body, "elevator_required")
    crew_size = validate.req_int(body, "crew_size", minimum=1)
    phase = state.phases[phase_id]
    # Step 6: end_at strictly after start_at.
    if end_at <= start_at:
        errors.date_window("end_at must be strictly after start_at")
    # Step 8: phase must be SCHEDULED or DELIVERED (PRD 3.7).
    if phase["logistics_status"] not in ("SCHEDULED", "DELIVERED"):
        errors.invalid_state("Windows may be booked only for SCHEDULED or DELIVERED phases")
    # Gate 13: union minimum crew.
    if union_required and crew_size < constants.UNION_MIN_CREW:
        errors.err("ERR_UNION_CREW_MINIMUM", 422,
                   "union_required windows need crew_size >= 4")
    zone = phase["building_zone_id"]
    # Gate 23: freight-elevator exclusivity with turnover buffer.
    if elevator_required and calc.elevator_conflict(zone, start_at, end_at):
        errors.err("ERR_WINDOW_CONFLICT", 409,
                   "Freight-elevator overlap within the 15-minute turnover buffer")
    # Gate 29: zone crew aggregate capacity.
    if calc.crew_capacity_exceeded(zone, start_at, end_at, crew_size):
        errors.err("ERR_ZONE_CREW_CAPACITY", 422,
                   "Zone crew aggregate capacity exceeded for a touched date")
    window = _new_entity({
        "installation_phase_id": phase_id,
        "building_zone_id": zone,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "union_required": union_required,
        "elevator_required": elevator_required,
        "crew_size": crew_size,
        "status": "RESERVED",
    })
    state.windows[window["id"]] = window
    return envelope.success_object(serialize.window(window), status=201)


@bp.get("/install-windows")
def list_windows():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    items = [w for w in state.windows.values()
             if _window_visible_to(w, role, user_id)]
    phase_filter = request.args.get("installation_phase_id")
    if phase_filter is not None:
        items = [w for w in items if w["installation_phase_id"] == phase_filter]
    zone_filter = request.args.get("building_zone_id")
    if zone_filter is not None:
        items = [w for w in items if w["building_zone_id"] == zone_filter]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.window(w) for w in page], total, limit, offset)


@bp.get("/install-windows/<windowId>")
def get_window(windowId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    window = _load_window(windowId)
    if not _window_visible_to(window, role, user_id):
        errors.forbidden_ownership()
    return envelope.success_object(serialize.window(window))


@bp.post("/install-windows/<windowId>/cancel")
def cancel_window(windowId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    window = _load_window(windowId)
    if not _window_visible_to(window, role, user_id):
        errors.forbidden_ownership()
    validate.body_json(request)
    if window["status"] != "RESERVED":
        errors.invalid_state("Only a RESERVED window can be cancelled")
    window["status"] = "CANCELLED"
    state.touch(window)
    # Freed elevator interval and crew capacity are implicit: conflict and crew
    # rules only consider RESERVED windows (PRD 3.7).
    return envelope.success_object(serialize.window(window))
