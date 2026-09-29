"""Route plan submission, the six geometry gates and the plan lifecycle."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_enum,
    check_int,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("plans", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "RemoteOperator")
PLAN_STATES = ("DRAFT", "VALIDATED", "ACTIVE", "SUPERSEDED", "REJECTED")
PLAN_ACTIONS = ("VALIDATE", "ACTIVATE", "REJECT")
REJECTION_REASONS = ("OPERATOR_REJECTED", "SEGMENT_BLOCKED", "REPLACED_BY_NEWER")
MISSION_TERMINAL = ("COMPLETED", "ABORTED")


@bp.get("/route-plans")
def list_plans():
    authorize(READ_ROLES)
    limit, offset = pagination()
    mission_id = arg_str("mission_id")
    plan_state = arg_enum("plan_state", PLAN_STATES)
    rows = []
    for plan in db.plans.values():
        if mission_id is not None and plan["mission_id"] != mission_id:
            continue
        if plan_state is not None and plan["plan_state"] != plan_state:
            continue
        rows.append(plan)
    return serve_list(rows, limit, offset, sort_key=lambda r: (r["revision_index"], r["_seq"]))


@bp.get("/route-plans/<plan_id>")
def get_plan(plan_id):
    authorize(READ_ROLES)
    return object_response(public(must("plans", plan_id)))


def _window_bounds(zone, moment):
    start_text = zone["operating_window_start_utc_hhmm"]
    end_text = zone["operating_window_end_utc_hhmm"]
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = day + timedelta(
        hours=int(start_text[0:2]), minutes=int(start_text[2:4])
    )
    window_end = day + timedelta(hours=int(end_text[0:2]), minutes=int(end_text[2:4]))
    return window_start, window_end


@bp.post("/route-plans")
def create_plan():
    authorize(("FleetDispatcher",))
    payload = body()
    for name in ("mission_id", "segment_sequence", "expected_delivery_mission_version"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    mission_id = check_str(payload, "mission_id", 1, None)
    expected_version = check_int(payload, "expected_delivery_mission_version", ge=0)

    sequence = payload["segment_sequence"]
    if not isinstance(sequence, list):
        raise bad("Field 'segment_sequence' must be an array of segment identifiers.")
    if len(sequence) == 0:
        raise bad("Field 'segment_sequence' must contain at least one segment.")
    seen = set()
    for entry in sequence:
        if not isinstance(entry, str) or entry == "":
            raise bad("Field 'segment_sequence' must contain segment identifiers.")
        if entry in seen:
            raise bad("Field 'segment_sequence' may not repeat a segment.")
        seen.add(entry)

    segments = [must("segments", entry) for entry in sequence]
    mission = must("missions", mission_id)

    if mission["version"] != expected_version:
        raise ApiError("ERR_STALE_MISSION_VERSION")

    if mission["mission_state"] in MISSION_TERMINAL:
        raise ApiError("ERR_MISSION_ALREADY_TERMINAL")

    robot = db.robots.get(mission["robot_id"])
    zone = db.zones.get(robot["zone_id"]) if robot is not None else None
    order = db.orders.get(mission["order_id"])

    total_length = calc.route_total_length_m(segments)
    crossing_count = calc.route_crossing_count(segments)
    clearance_margin = calc.route_clearance_margin(segments, robot)
    duration = calc.planned_duration_min(total_length, robot)

    # gate 1 - route clearance
    if calc.dec(clearance_margin) < 0:
        raise ApiError("ERR_CLEARANCE_INSUFFICIENT")

    # gate 2 - crossing risk ceiling
    if zone is not None:
        scores = [
            calc.dec(s["crossing_risk_score"])
            for s in segments
            if s["crossing_risk_score"] is not None
        ]
        if scores and max(scores) > calc.dec(zone["max_crossing_risk"]):
            raise ApiError("ERR_CROSSING_RISK_EXCEEDED")

    # gate 3 - operating-window containment
    if zone is not None:
        start = now()
        finish = start + timedelta(minutes=duration)
        window_start, window_end = _window_bounds(zone, start)
        if start < window_start or finish > window_end:
            raise ApiError("ERR_CURFEW_WINDOW_VIOLATION")

    # gate 4 - contiguity
    for index in range(len(segments) - 1):
        if segments[index + 1]["id"] not in segments[index]["connected_segment_ids"]:
            raise ApiError("ERR_ROUTE_NOT_CONTIGUOUS")

    # gate 5 - termination at the order's dropoff segment
    if order is not None and segments[-1]["id"] != order["dropoff_segment_id"]:
        raise ApiError("ERR_ROUTE_DROPOFF_MISMATCH")

    # gate 6 - every segment inside the mission robot's zone
    if robot is not None:
        for segment in segments:
            if segment["zone_id"] != robot["zone_id"]:
                raise ApiError(
                    "ERR_ZONE_MISMATCH",
                    "A route segment belongs to a different zone than the mission's robot.",
                )

    revision_index = (
        len([p for p in db.plans.values() if p["mission_id"] == mission["id"]]) + 1
    )

    plan = create_row(
        db.plans,
        {
            "mission_id": mission["id"],
            "segment_sequence": [s["id"] for s in segments],
            "plan_state": "DRAFT",
            "total_length_m": total_length,
            "crossing_count": crossing_count,
            "clearance_margin_cm": clearance_margin,
            "planned_duration_min": duration,
            "revision_index": revision_index,
            "supersedes_plan_id": None,
            "rejection_reason": None,
        },
    )
    return object_response(public(plan), 201)


@bp.post("/route-plans/<plan_id>/transitions")
def plan_transition(plan_id):
    authorize(("FleetDispatcher",))
    payload = body()
    action = check_enum(payload, "action", PLAN_ACTIONS)
    rejection_reason = None
    if action == "REJECT":
        rejection_reason = check_enum(payload, "rejection_reason", REJECTION_REASONS)

    plan = must("plans", plan_id)
    mission = db.missions.get(plan["mission_id"])

    if action == "VALIDATE":
        if plan["plan_state"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        segments = [db.segments.get(sid) for sid in plan["segment_sequence"]]
        for segment in segments:
            if segment is None or segment["status"] not in ("APPROVED", "BLOCKED"):
                raise ApiError("ERR_SEGMENT_NOT_APPROVED")
        for segment in segments:
            if segment["status"] == "BLOCKED":
                raise ApiError("ERR_SEGMENT_BLOCKED")
        plan["plan_state"] = "VALIDATED"
        bump(plan)
    elif action == "ACTIVATE":
        if plan["plan_state"] != "VALIDATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if mission is None or mission["mission_state"] not in ("PLANNED", "LOADED", "BLOCKED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The mission cannot take a new active route in its current state.",
            )
        for sid in plan["segment_sequence"]:
            segment = db.segments.get(sid)
            if segment is not None and segment["status"] == "BLOCKED":
                raise ApiError("ERR_SEGMENT_BLOCKED")

        previous = None
        for candidate in cascades.by_created(
            [
                p
                for p in db.plans.values()
                if p["mission_id"] == mission["id"]
                and p["plan_state"] == "ACTIVE"
                and p["id"] != plan["id"]
            ]
        ):
            previous = candidate
            candidate["plan_state"] = "SUPERSEDED"
            candidate["rejection_reason"] = "REPLACED_BY_NEWER"
            bump(candidate)

        plan["plan_state"] = "ACTIVE"
        plan["supersedes_plan_id"] = previous["id"] if previous is not None else None
        bump(plan)
        mission["active_route_plan_id"] = plan["id"]
        bump(mission)
    else:  # REJECT
        if plan["plan_state"] not in ("DRAFT", "VALIDATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        plan["plan_state"] = "REJECTED"
        plan["rejection_reason"] = rejection_reason
        bump(plan)

    return object_response(public(plan))
