"""Staffer and lane-assignment endpoints (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers
from calc import ZERO, hours_between
from common import list_response
from envelope import ok
from errors import ApiError
from rollups import assignments_of_staffer, refresh_world
from store import new_row, set_and_touch, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    opt_enum,
    opt_str,
    req_date,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("staff", __name__)

ROLE_CODES = ["TRAFFIC", "UNLOAD", "CHEMIST", "SUPERVISOR"]


@bp.post("/hhw/staffers")
def create_staffer():
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    program_id = req_str(payload, "program_id")
    full_name = req_str(payload, "full_name")
    role_code = req_enum(payload, "role_code", ROLE_CODES)
    expires_on = req_date(payload, "hazwoper_expires_on")
    status = opt_enum(payload, "status", ["ACTIVE", "INACTIVE"], "ACTIVE")

    program = lookup("program", program_id)

    row = new_row({
        "program_id": program["id"],
        "full_name": full_name,
        "role_code": role_code,
        "hazwoper_expires_on": expires_on,
        "status": status,
        "assigned_hours": ZERO,
    })
    store.staffers[row["id"]] = row
    refresh_world()
    return ok(serializers.staffer(row), 201)


@bp.get("/hhw/staffers")
def list_staffers():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "status": request.args.get("status"),
        "role_code": request.args.get("role_code"),
    }
    return list_response(request.args, list(store.staffers.values()),
                         serializers.staffer, filters)


@bp.get("/hhw/staffers/<staffer_id>")
def read_staffer(staffer_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.staffer(lookup("staffer", staffer_id)))


@bp.post("/hhw/lane-assignments")
def create_lane_assignment():
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    event_id = req_str(payload, "event_id")
    staffer_id = req_str(payload, "staffer_id")
    lane_number = req_int(payload, "lane_number", minimum=1)
    start_utc = req_dt(payload, "start_utc")
    end_utc = req_dt(payload, "end_utc")
    if end_utc <= start_utc:
        raise ApiError("ERR_INVALID_REQUEST",
                       "end_utc must be strictly after start_utc.")

    event = lookup("event", event_id)
    staffer = lookup("staffer", staffer_id)

    if start_utc < event["_window_start_dt"] or end_utc > event["_window_end_dt"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The staffing interval must lie inside the event window.")
    duration = hours_between(start_utc, end_utc)
    if duration <= ZERO or duration > calc.MAX_SHIFT_HOURS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "duration_hours must be greater than 0 and at most 12.0.")

    # Rung 17 — HAZWOPER certification and roster status.
    if staffer["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICATION_EXPIRED")
    if staffer["hazwoper_expires_on"] < event["event_date"]:
        raise ApiError("ERR_CERTIFICATION_EXPIRED")

    # Rung 23 — half-open interval versus a trailing 30-minute decon buffer.
    decon = timedelta(seconds=calc.DECON_BUFFER_SECONDS)
    for existing in assignments_of_staffer(staffer["id"]):
        if existing["status"] != "ACTIVE":
            continue
        band_start = existing["_start_dt"]
        band_end = existing["_end_dt"] + decon
        if start_utc < band_end and end_utc > band_start:
            raise ApiError("ERR_STAFFER_INTERVAL_CONFLICT")

    row = new_row({
        "event_id": event["id"],
        "staffer_id": staffer["id"],
        "lane_number": lane_number,
        "start_utc": payload["start_utc"],
        "end_utc": payload["end_utc"],
        "_start_dt": start_utc,
        "_end_dt": end_utc,
        "duration_hours": duration,
        "status": "ACTIVE",
        "released_reason": None,
    })
    store.lane_assignments[row["id"]] = row
    refresh_world()
    return ok(serializers.lane_assignment(row), 201)


@bp.get("/hhw/lane-assignments")
def list_lane_assignments():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "event_id": request.args.get("event_id"),
        "staffer_id": request.args.get("staffer_id"),
        "status": request.args.get("status"),
    }
    return list_response(request.args, list(store.lane_assignments.values()),
                         serializers.lane_assignment, filters)


@bp.get("/hhw/lane-assignments/<assignment_id>")
def read_lane_assignment(assignment_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.lane_assignment(lookup("lane_assignment", assignment_id)))


@bp.post("/hhw/lane-assignments/<assignment_id>/release")
def release_lane_assignment(assignment_id):
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    released_reason = opt_str(payload, "released_reason")

    assignment = lookup("lane_assignment", assignment_id)
    if assignment["status"] != "ACTIVE":                                # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    set_and_touch(assignment, status="RELEASED", released_reason=released_reason)
    refresh_world()
    return ok(serializers.lane_assignment(assignment))
