"""Sidewalk segment mapping, survey/approval lifecycle and symmetric adjacency."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_bool,
    check_enum,
    check_number,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("segments", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "RemoteOperator", "SafetyOfficer")
SEGMENT_TYPES = ("WALKWAY", "CROSSING", "RAMP")
CROSSING_CONTROLS = ("NONE", "SIGNALIZED", "UNSIGNALIZED", "MIDBLOCK")
SEGMENT_STATUSES = ("MAPPED", "SURVEYED", "APPROVED", "BLOCKED", "RETIRED")
SEGMENT_ACTIONS = ("SURVEY", "APPROVE", "RETIRE")


@bp.get("/sidewalk-segments")
def list_segments():
    authorize(READ_ROLES)
    limit, offset = pagination()
    zone_id = arg_str("zone_id")
    status = arg_enum("status", SEGMENT_STATUSES)
    segment_type = arg_enum("segment_type", SEGMENT_TYPES)
    rows = []
    for segment in db.segments.values():
        if zone_id is not None and segment["zone_id"] != zone_id:
            continue
        if status is not None and segment["status"] != status:
            continue
        if segment_type is not None and segment["segment_type"] != segment_type:
            continue
        rows.append(segment)
    return serve_list(rows, limit, offset)


@bp.get("/sidewalk-segments/<segment_id>")
def get_segment(segment_id):
    authorize(READ_ROLES)
    return object_response(public(must("segments", segment_id)))


@bp.post("/sidewalk-segments")
def create_segment():
    authorize(("PlatformAdmin",))
    payload = body()
    for name in (
        "zone_id",
        "segment_code",
        "segment_type",
        "length_m",
        "measured_clearance_cm",
        "surface_grade_pct",
    ):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)

    segment_type = check_enum(payload, "segment_type", SEGMENT_TYPES)
    crossing_control = check_enum(
        payload, "crossing_control", CROSSING_CONTROLS, required=False
    )
    if crossing_control is None:
        crossing_control = "NONE"
    zone_id = check_str(payload, "zone_id", 1, None)
    segment_code = check_str(payload, "segment_code", 1, None)
    length_m = check_number(payload, "length_m", gt=0)
    measured_clearance_cm = check_number(payload, "measured_clearance_cm", gt=0)
    surface_grade_pct = check_number(payload, "surface_grade_pct", ge=0, le=25)
    sightline_m = check_number(payload, "sightline_m", ge=0, required=False, default=0.0)
    pedestrian_flow = check_number(
        payload, "pedestrian_flow_per_min", ge=0, required=False, default=0.0
    )
    curb_ramp_present = check_bool(payload, "curb_ramp_present", required=False, default=False)

    raw_connected = payload.get("connected_segment_ids")
    if raw_connected is None:
        raw_connected = []
    if not isinstance(raw_connected, list):
        raise bad("Field 'connected_segment_ids' must be an array of segment identifiers.")
    connected = []
    for entry in raw_connected:
        if not isinstance(entry, str) or entry == "":
            raise bad("Field 'connected_segment_ids' must contain segment identifiers.")
        if entry not in connected:
            connected.append(entry)

    zone = must("zones", zone_id)
    neighbours = [must("segments", entry) for entry in connected]

    for neighbour in neighbours:
        if neighbour["zone_id"] != zone["id"]:
            raise ApiError(
                "ERR_ZONE_MISMATCH",
                "An adjacent segment belongs to a different service zone.",
            )

    for existing in db.segments.values():
        if existing["zone_id"] == zone["id"] and existing["segment_code"] == segment_code:
            raise bad("Field 'segment_code' must be unique within the service zone.")

    segment = create_row(
        db.segments,
        {
            "zone_id": zone["id"],
            "segment_code": segment_code,
            "segment_type": segment_type,
            "crossing_control": crossing_control,
            "length_m": length_m,
            "measured_clearance_cm": measured_clearance_cm,
            "surface_grade_pct": surface_grade_pct,
            "sightline_m": sightline_m,
            "pedestrian_flow_per_min": pedestrian_flow,
            "curb_ramp_present": curb_ramp_present,
            "crossing_risk_score": None,
            "status": "MAPPED",
            "connected_segment_ids": list(connected),
            "blocked_by_closure_id": None,
        },
    )

    # symmetric closure: adding B to A also adds A to B
    for neighbour in cascades.by_created(neighbours):
        if segment["id"] not in neighbour["connected_segment_ids"]:
            neighbour["connected_segment_ids"].append(segment["id"])
            bump(neighbour)

    return object_response(public(segment), 201)


@bp.post("/sidewalk-segments/<segment_id>/transitions")
def segment_transition(segment_id):
    authorize(("PlatformAdmin",))
    payload = body()
    action = check_enum(payload, "action", SEGMENT_ACTIONS)

    overrides = {}
    if action == "SURVEY":
        overrides["sightline_m"] = check_number(payload, "sightline_m", ge=0, required=False)
        overrides["pedestrian_flow_per_min"] = check_number(
            payload, "pedestrian_flow_per_min", ge=0, required=False
        )
        overrides["curb_ramp_present"] = check_bool(
            payload, "curb_ramp_present", required=False
        )
        overrides["measured_clearance_cm"] = check_number(
            payload, "measured_clearance_cm", gt=0, required=False
        )

    segment = must("segments", segment_id)
    zone = db.zones.get(segment["zone_id"])

    if action == "SURVEY":
        if segment["status"] != "MAPPED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for key, value in overrides.items():
            if value is not None:
                segment[key] = value
        segment["crossing_risk_score"] = calc.crossing_risk_score(segment)
        segment["status"] = "SURVEYED"
        bump(segment)
    elif action == "APPROVE":
        if segment["status"] != "SURVEYED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        score = segment["crossing_risk_score"]
        if zone is not None and score is not None:
            if calc.dec(score) > calc.dec(zone["max_crossing_risk"]):
                raise ApiError("ERR_CROSSING_RISK_EXCEEDED")
        if zone is not None:
            if calc.dec(segment["measured_clearance_cm"]) < calc.dec(
                zone["ordinance_min_clearance_cm"]
            ):
                raise ApiError("ERR_CLEARANCE_INSUFFICIENT")
        segment["status"] = "APPROVED"
        bump(segment)
    else:  # RETIRE
        if segment["status"] not in ("SURVEYED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for plan in db.plans.values():
            if plan["plan_state"] == "ACTIVE" and segment["id"] in plan["segment_sequence"]:
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "An active route plan still names this segment.",
                )
        neighbours = [
            db.segments[nid]
            for nid in segment["connected_segment_ids"]
            if nid in db.segments
        ]
        segment["status"] = "RETIRED"
        bump(segment)
        for neighbour in cascades.by_created(neighbours):
            if segment["id"] in neighbour["connected_segment_ids"]:
                neighbour["connected_segment_ids"] = [
                    nid for nid in neighbour["connected_segment_ids"] if nid != segment["id"]
                ]
                bump(neighbour)

    return object_response(public(segment))
