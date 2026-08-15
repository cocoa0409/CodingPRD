"""Tunnels and tunnel bookings (PRD §3.5): trailing-buffer conflict and
throughput checks, one active booking per run."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_BOOKING_EXISTS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RUN_NOT_SCHEDULABLE,
    ERR_TUNNEL_CAPACITY_EXCEEDED,
    ERR_TUNNEL_WINDOW_CONFLICT,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import serialize, tunnel_throughput_ok, tunnel_window_conflicts
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = Blueprint("tunnels", __name__)

TUNNEL_SPEC = {
    "tunnel_code": {"type": "string", "required": True},
    "max_units_per_hour": {"type": "integer", "min": 1, "required": True},
}

BOOKING_SPEC = {
    "tunnel_id": {"type": "string", "required": True},
    "run_id": {"type": "string", "required": True},
    "start_at": {"type": "datetime", "required": True},
    "end_at": {"type": "datetime", "required": True},
}


@bp.route("/tunnels", methods=["POST"])
def create_tunnel():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, TUNNEL_SPEC)
    tunnel = db.new_entity("tunnels", {
        "tunnel_code": body["tunnel_code"],
        "max_units_per_hour": body["max_units_per_hour"],
    })
    return success_obj(serialize("tunnels", tunnel), 201)


@bp.route("/tunnels", methods=["GET"])
def list_tunnels():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("tunnels"), [])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("tunnels", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/tunnel-bookings", methods=["POST"])
def create_booking():
    authenticate({"ProductionPlanner"})
    body = body_json()
    exist_body_fks(body, {
        "tunnel_id": ("tunnels", "tunnel"),
        "run_id": ("runs", "production run"),
    })
    check_shape(body, BOOKING_SPEC)
    new_start = parse_dt(body["start_at"])
    new_end = parse_dt(body["end_at"])
    if new_end <= new_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_at must be after start_at")
    tunnel = db.get("tunnels", body["tunnel_id"])
    run = db.get("runs", body["run_id"])
    # Priority 15: window conflict (trailing 30-minute buffer, half-open).
    if tunnel_window_conflicts(tunnel["id"], new_start, new_end):
        raise ApiError(
            ERR_TUNNEL_WINDOW_CONFLICT,
            409,
            "booking window conflicts with an existing booking (incl. cleanup buffer)",
        )
    # Priority 16: throughput — planned_units <= max_units_per_hour * hours.
    if not tunnel_throughput_ok(tunnel, run["planned_units"], new_start, new_end):
        raise ApiError(
            ERR_TUNNEL_CAPACITY_EXCEEDED,
            422,
            "planned units exceed tunnel throughput for the window",
        )
    # Priority 17: the referenced run must be SCHEDULED or MIX_ASSIGNED.
    if run["status"] not in ("SCHEDULED", "MIX_ASSIGNED"):
        raise ApiError(
            ERR_RUN_NOT_SCHEDULABLE, 422, "run is not SCHEDULED or MIX_ASSIGNED"
        )
    # Priority 18: at most one active (BOOKED) booking per run.
    for existing in db.all_of("bookings"):
        if existing["run_id"] == run["id"] and existing["status"] == "BOOKED":
            raise ApiError(ERR_BOOKING_EXISTS, 409, "run already has a BOOKED booking")
    booking = db.new_entity("bookings", {
        "tunnel_id": tunnel["id"],
        "run_id": run["id"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "BOOKED",
    })
    return success_obj(serialize("bookings", booking), 201)


@bp.route("/tunnel-bookings", methods=["GET"])
def list_bookings():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("bookings"), ["tunnel_id", "run_id", "status"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("bookings", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/tunnel-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    authenticate(ALL_ROLES)
    booking = path_entity("bookings", booking_id, "tunnel booking")
    return success_obj(serialize("bookings", booking))


@bp.route("/tunnel-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    authenticate({"ProductionPlanner"})
    booking = path_entity("bookings", booking_id, "tunnel booking")
    if booking["status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409, "booking is not BOOKED")
    booking["status"] = "CANCELED"
    db.touch(booking)
    return success_obj(serialize("bookings", booking))
