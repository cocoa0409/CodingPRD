"""Service zone provisioning, permit lifecycle and unit economics."""

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
    check_enum,
    check_hhmm,
    check_int,
    check_number,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("zones", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "FleetDispatcher",
    "RemoteOperator",
    "SafetyOfficer",
    "CustomerSupport",
)
ECONOMICS_ROLES = ("PlatformAdmin", "FleetDispatcher")
PERMIT_STATES = ("PROVISIONED", "PERMITTED", "RESTRICTED", "REVOKED")
PERMIT_ACTIONS = ("ACTIVATE_PERMIT", "RESTRICT", "LIFT_RESTRICTION", "REVOKE")


_refresh_budget = cascades.refresh_zone_budget


@bp.get("/service-zones")
def list_zones():
    authorize(READ_ROLES)
    limit, offset = pagination()
    permit_state = arg_enum("permit_state", PERMIT_STATES)
    municipality_code = arg_str("municipality_code")
    rows = []
    for zone in db.zones.values():
        if permit_state is not None and zone["permit_state"] != permit_state:
            continue
        if municipality_code is not None and zone["municipality_code"] != municipality_code:
            continue
        _refresh_budget(zone)
        rows.append(zone)
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return serve_list(rows, limit, offset, sort_key=lambda r: 0)


@bp.get("/service-zones/<zone_id>")
def get_zone(zone_id):
    authorize(READ_ROLES)
    zone = must("zones", zone_id)
    _refresh_budget(zone)
    return object_response(public(zone))


@bp.get("/service-zones/<zone_id>/economics")
def get_zone_economics(zone_id):
    authorize(ECONOMICS_ROLES)
    zone = must("zones", zone_id)
    return object_response(calc.zone_economics(zone))


@bp.post("/service-zones")
def create_zone():
    authorize(("PlatformAdmin",))
    payload = body()
    required = (
        "name",
        "municipality_code",
        "ordinance_min_clearance_cm",
        "ordinance_max_speed_cm_s",
        "operating_window_start_utc_hhmm",
        "operating_window_end_utc_hhmm",
        "max_concurrent_robots",
        "planning_haul_m",
        "planning_crossings",
        "remedy_budget_cents",
    )
    for name in required:
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)

    name = check_str(payload, "name", 1, 120)
    municipality_code = check_str(payload, "municipality_code", 2, 12)
    min_clearance = check_number(payload, "ordinance_min_clearance_cm", gt=0)
    max_speed = check_int(payload, "ordinance_max_speed_cm_s", gt=0)
    max_concurrent = check_int(payload, "max_concurrent_robots", ge=1)
    max_crossing_risk = check_number(
        payload, "max_crossing_risk", ge=0, le=100, required=False, default=45.0
    )
    takeover_threshold = check_int(
        payload, "takeover_confidence_threshold_pct", ge=0, le=100, required=False, default=35
    )
    planning_haul_m = check_number(payload, "planning_haul_m", gt=0)
    planning_crossings = check_int(payload, "planning_crossings", ge=0)
    remedy_budget = check_int(payload, "remedy_budget_cents", ge=0)
    insurer_threshold = check_int(
        payload, "insurer_notify_threshold_cents", ge=0, required=False, default=25000
    )
    window_start = check_hhmm(payload, "operating_window_start_utc_hhmm")
    window_end = check_hhmm(payload, "operating_window_end_utc_hhmm")
    if not window_end > window_start:
        raise bad(
            "Field 'operating_window_end_utc_hhmm' must be strictly greater than "
            "'operating_window_start_utc_hhmm'."
        )

    zone = create_row(
        db.zones,
        {
            "name": name,
            "municipality_code": municipality_code,
            "permit_state": "PROVISIONED",
            "ordinance_min_clearance_cm": min_clearance,
            "ordinance_max_speed_cm_s": max_speed,
            "operating_window_start_utc_hhmm": window_start,
            "operating_window_end_utc_hhmm": window_end,
            "max_concurrent_robots": max_concurrent,
            "max_crossing_risk": max_crossing_risk,
            "takeover_confidence_threshold_pct": takeover_threshold,
            "planning_haul_m": planning_haul_m,
            "planning_crossings": planning_crossings,
            "remedy_budget_cents": remedy_budget,
            "remedy_spent_cents": 0,
            "remedy_budget_remaining_cents": remedy_budget,
            "reserved_bay_minutes": 0,
            "open_incident_count": 0,
            "on_mission_robot_count": 0,
            "insurer_notify_threshold_cents": insurer_threshold,
            "lid_code_sequence": 0,
            "restriction_reason": None,
        },
    )
    return object_response(public(zone), 201)


@bp.post("/service-zones/<zone_id>/permit-transitions")
def permit_transition(zone_id):
    authorize(("PlatformAdmin",))
    payload = body()
    action = check_enum(payload, "action", PERMIT_ACTIONS)
    reason = None
    if action in ("RESTRICT", "REVOKE"):
        reason = check_str(payload, "reason", 1, None)

    zone = must("zones", zone_id)
    _refresh_budget(zone)
    state = zone["permit_state"]

    if action == "ACTIVATE_PERMIT":
        if state != "PROVISIONED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        approved = any(
            s["zone_id"] == zone["id"] and s["status"] == "APPROVED" for s in db.segments.values()
        )
        if not approved:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The zone needs at least one APPROVED sidewalk segment before its permit "
                "can be activated.",
            )
        zone["permit_state"] = "PERMITTED"
        zone["restriction_reason"] = None
        bump(zone)
    elif action == "RESTRICT":
        if state != "PERMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        zone["permit_state"] = "RESTRICTED"
        zone["restriction_reason"] = reason
        bump(zone)
    elif action == "LIFT_RESTRICTION":
        if state != "RESTRICTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        zone["permit_state"] = "PERMITTED"
        zone["restriction_reason"] = None
        bump(zone)
    else:  # REVOKE
        if state not in ("PERMITTED", "RESTRICTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        cascades.revoke_zone(zone, reason)

    _refresh_budget(zone)
    return object_response(public(zone))
