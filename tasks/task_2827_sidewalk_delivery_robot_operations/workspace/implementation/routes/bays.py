"""Depot bays and the exclusive bay-window reservation ledger."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now, parse_ts, plus_minutes, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_enum,
    check_int,
    check_number,
    check_str,
    check_timestamp,
    pagination,
)
from response import object_response

bp = Blueprint("bays", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher")
BAY_TYPES = ("CHARGE", "STAGE", "SERVICE")
BAY_STATES = ("OPEN", "OUT_OF_SERVICE")
RESERVATION_STATES = ("HELD", "ACTIVE", "RELEASED", "CANCELLED")
RESERVATION_ACTIONS = ("ACTIVATE", "RELEASE", "CANCEL")


# ------------------------------------------------------------------ depot bays


@bp.get("/depot-bays")
def list_bays():
    authorize(READ_ROLES)
    limit, offset = pagination()
    zone_id = arg_str("zone_id")
    bay_type = arg_enum("bay_type", BAY_TYPES)
    state = arg_enum("state", BAY_STATES)
    rows = []
    for bay in db.bays.values():
        if zone_id is not None and bay["zone_id"] != zone_id:
            continue
        if bay_type is not None and bay["bay_type"] != bay_type:
            continue
        if state is not None and bay["state"] != state:
            continue
        rows.append(bay)
    return serve_list(rows, limit, offset)


@bp.get("/depot-bays/<bay_id>")
def get_bay(bay_id):
    authorize(READ_ROLES)
    return object_response(public(must("bays", bay_id)))


@bp.post("/depot-bays")
def create_bay():
    authorize(("PlatformAdmin",))
    payload = body()
    for name in ("zone_id", "bay_code", "bay_type"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    bay_type = check_enum(payload, "bay_type", BAY_TYPES)
    state = check_enum(payload, "state", BAY_STATES, required=False)
    if state is None:
        state = "OPEN"
    zone_id = check_str(payload, "zone_id", 1, None)
    bay_code = check_str(payload, "bay_code", 1, None)
    power_kw = check_number(payload, "power_kw", ge=0, required=False, default=0.0)

    zone = must("zones", zone_id)

    for existing in db.bays.values():
        if existing["zone_id"] == zone["id"] and existing["bay_code"] == bay_code:
            raise bad("Field 'bay_code' must be unique within the service zone.")

    bay = create_row(
        db.bays,
        {
            "zone_id": zone["id"],
            "bay_code": bay_code,
            "bay_type": bay_type,
            "power_kw": power_kw,
            "state": state,
            "committed_minutes": 0,
        },
    )
    return object_response(public(bay), 201)


# ------------------------------------------------------------- reservations


@bp.get("/bay-reservations")
def list_reservations():
    authorize(READ_ROLES)
    limit, offset = pagination()
    bay_id = arg_str("bay_id")
    robot_id = arg_str("robot_id")
    state = arg_enum("state", RESERVATION_STATES)
    reservation_type = arg_enum("reservation_type", BAY_TYPES)
    rows = []
    for reservation in db.reservations.values():
        if bay_id is not None and reservation["bay_id"] != bay_id:
            continue
        if robot_id is not None and reservation["robot_id"] != robot_id:
            continue
        if state is not None and reservation["state"] != state:
            continue
        if (
            reservation_type is not None
            and reservation["reservation_type"] != reservation_type
        ):
            continue
        rows.append(reservation)
    return serve_list(rows, limit, offset)


@bp.get("/bay-reservations/<reservation_id>")
def get_reservation(reservation_id):
    authorize(READ_ROLES)
    return object_response(public(must("reservations", reservation_id)))


def _window_conflict(bay, start_iso, end_iso, ignore_id=None):
    buffer_min = calc.TURNAROUND_BUFFER_MINUTES
    new_start = parse_ts(start_iso)
    new_end = parse_ts(end_iso)
    for existing in db.reservations.values():
        if existing["bay_id"] != bay["id"]:
            continue
        if existing["state"] not in calc.LEDGER_ACTIVE_STATES:
            continue
        if ignore_id is not None and existing["id"] == ignore_id:
            continue
        held_start = parse_ts(existing["window_start_utc"])
        held_end = parse_ts(existing["window_end_utc"])
        if new_start < plus_minutes(held_end, buffer_min) and plus_minutes(
            new_end, buffer_min
        ) > held_start:
            return True
    return False


@bp.post("/bay-reservations")
def create_reservation():
    authorize(("FleetDispatcher",))
    payload = body()
    for name in ("bay_id", "robot_id", "reservation_type", "window_start_utc", "window_end_utc"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    reservation_type = check_enum(payload, "reservation_type", BAY_TYPES)
    bay_id = check_str(payload, "bay_id", 1, None)
    robot_id = check_str(payload, "robot_id", 1, None)
    window_start = check_timestamp(payload, "window_start_utc")
    window_end = check_timestamp(payload, "window_end_utc")
    if parse_ts(window_end) <= parse_ts(window_start):
        raise bad("Field 'window_end_utc' must be strictly after 'window_start_utc'.")
    if "expected_depot_bay_version" not in payload or payload["expected_depot_bay_version"] is None:
        raise bad("Field 'expected_depot_bay_version' is required.")
    expected_version = check_int(payload, "expected_depot_bay_version", ge=0)

    robot = must("robots", robot_id)
    bay = must("bays", bay_id)

    if bay["version"] != expected_version:
        raise ApiError("ERR_STALE_BAY_VERSION")

    if bay["zone_id"] != robot["zone_id"]:
        raise ApiError(
            "ERR_ZONE_MISMATCH", "The depot bay belongs to a different zone than the robot."
        )

    if _window_conflict(bay, window_start, window_end):
        raise ApiError("ERR_BAY_WINDOW_CONFLICT")

    if reservation_type != bay["bay_type"]:
        raise ApiError("ERR_BAY_TYPE_MISMATCH")

    if bay["state"] != "OPEN":
        raise ApiError("ERR_BAY_OUT_OF_SERVICE")

    minutes = calc.window_minutes(window_start, window_end)

    reservation = create_row(
        db.reservations,
        {
            "bay_id": bay["id"],
            "robot_id": robot["id"],
            "reservation_type": reservation_type,
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "window_minutes": minutes,
            "state": "HELD",
        },
    )
    cascades.add_bay_minutes(bay, minutes)
    return object_response(public(reservation), 201)


@bp.post("/bay-reservations/<reservation_id>/transitions")
def reservation_transition(reservation_id):
    authorize(("FleetDispatcher",))
    payload = body()
    action = check_enum(payload, "action", RESERVATION_ACTIONS)
    reservation = must("reservations", reservation_id)
    bay = db.bays.get(reservation["bay_id"])

    if action == "ACTIVATE":
        if reservation["state"] != "HELD":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        current = now()
        if not (
            parse_ts(reservation["window_start_utc"])
            <= current
            < parse_ts(reservation["window_end_utc"])
        ):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The logical clock is outside the reservation window.",
            )
        if bay is None or bay["state"] != "OPEN":
            raise ApiError("ERR_BAY_OUT_OF_SERVICE")
        reservation["state"] = "ACTIVE"
        bump(reservation)
    elif action == "RELEASE":
        if reservation["state"] != "ACTIVE":
            raise ApiError("ERR_RESERVATION_NOT_ACTIVE")
        cascades.cancel_reservation_row(reservation, "RELEASED")
    else:  # CANCEL
        if reservation["state"] != "HELD":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        cascades.cancel_reservation_row(reservation, "CANCELLED")

    return object_response(public(reservation))
