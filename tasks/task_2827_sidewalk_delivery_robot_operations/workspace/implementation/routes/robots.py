"""Robot registration, the two parallel state dimensions and telemetry."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, public
from errors import ApiError, bad
from middleware import (
    arg_bool,
    arg_enum,
    arg_str,
    authorize,
    body,
    check_bool,
    check_enum,
    check_int,
    check_number,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("robots", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "RemoteOperator", "SafetyOfficer")
DUTY_STATES = (
    "OFFLINE",
    "STAGING",
    "AVAILABLE",
    "ON_MISSION",
    "CHARGING",
    "MAINTENANCE",
    "RETIRED",
)
HEALTH_STATES = ("NOMINAL", "DEGRADED", "IMPAIRED", "QUARANTINED")
DUTY_ACTIONS = ("STAGE", "MAKE_AVAILABLE", "BEGIN_CHARGE", "BEGIN_MAINTENANCE", "RETIRE")
HEALTH_ACTIONS = ("DOWNGRADE", "IMPAIR", "QUARANTINE", "CLEAR")


@bp.get("/robots")
def list_robots():
    authorize(READ_ROLES)
    limit, offset = pagination()
    zone_id = arg_str("zone_id")
    duty_state = arg_enum("duty_state", DUTY_STATES)
    health_state = arg_enum("health_state", HEALTH_STATES)
    eligible_only = arg_bool("eligible_only")

    rows = []
    for robot in db.robots.values():
        if zone_id is not None and robot["zone_id"] != zone_id:
            continue
        if duty_state is not None and robot["duty_state"] != duty_state:
            continue
        if health_state is not None and robot["health_state"] != health_state:
            continue
        if eligible_only is True:
            zone = db.zones.get(robot["zone_id"])
            if not calc.robot_matches_core(robot, zone):
                continue
        rows.append(robot)

    if eligible_only is True:
        return serve_list(rows, limit, offset, sort_key=calc.selector_rank)
    return serve_list(rows, limit, offset)


@bp.get("/robots/<robot_id>")
def get_robot(robot_id):
    authorize(READ_ROLES)
    return object_response(public(must("robots", robot_id)))


@bp.post("/robots")
def create_robot():
    authorize(("PlatformAdmin",))
    payload = body()
    for name in (
        "zone_id",
        "asset_tag",
        "width_cm",
        "container_capacity_liters",
        "max_speed_cm_s",
    ):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    zone_id = check_str(payload, "zone_id", 1, None)
    asset_tag = check_str(payload, "asset_tag", 1, None)
    width_cm = check_number(payload, "width_cm", gt=0)
    capacity = check_number(payload, "container_capacity_liters", gt=0)
    max_speed = check_number(payload, "max_speed_cm_s", gt=0)

    zone = must("zones", zone_id)

    for existing in db.robots.values():
        if existing["asset_tag"] == asset_tag:
            raise bad("Field 'asset_tag' must be unique across the whole fleet.")

    if calc.dec(max_speed) > calc.dec(zone["ordinance_max_speed_cm_s"]):
        raise ApiError("ERR_ORDINANCE_SPEED_EXCEEDED")

    robot = create_row(
        db.robots,
        {
            "zone_id": zone["id"],
            "asset_tag": asset_tag,
            "width_cm": width_cm,
            "container_capacity_liters": capacity,
            "max_speed_cm_s": max_speed,
            "battery_pct": 100.0,
            "duty_state": "OFFLINE",
            "health_state": "NOMINAL",
            "odometer_m": 0.0,
            "yield_event_count": 0,
            "tamper_flag": False,
            "active_mission_id": None,
            "current_bay_reservation_id": None,
            "lifetime_mission_count": 0,
            "lifetime_intervention_count": 0,
            "lifetime_escalation_count": 0,
            "clean_mission_count": 0,
            "rolling_autonomy_index": 100,
            "lifetime_autonomy_index": 100,
        },
    )
    return object_response(public(robot), 201)


def _resolve_depot_reservation(robot, reservation_id, wanted_type):
    reservation = db.reservations.get(reservation_id)
    if reservation is None:
        raise ApiError("ERR_RESERVATION_NOT_ACTIVE")
    if reservation["state"] != "ACTIVE":
        raise ApiError("ERR_RESERVATION_NOT_ACTIVE")
    if reservation["reservation_type"] != wanted_type:
        raise ApiError("ERR_RESERVATION_NOT_ACTIVE")
    if reservation["robot_id"] != robot["id"]:
        raise ApiError("ERR_RESERVATION_NOT_ACTIVE")
    return reservation


@bp.post("/robots/<robot_id>/duty-transitions")
def duty_transition(robot_id):
    authorize(("FleetDispatcher",))
    payload = body()
    action = check_enum(payload, "action", DUTY_ACTIONS)
    reservation_id = None
    if action in ("BEGIN_CHARGE", "BEGIN_MAINTENANCE"):
        reservation_id = check_str(payload, "bay_reservation_id", 1, None)

    robot = must("robots", robot_id)
    zone = db.zones.get(robot["zone_id"])
    duty = robot["duty_state"]

    if action == "STAGE":
        if duty != "OFFLINE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if zone is None or zone["permit_state"] != "PERMITTED":
            raise ApiError("ERR_ZONE_NOT_PERMITTED")
        if robot["health_state"] == "QUARANTINED":
            raise ApiError("ERR_ROBOT_HEALTH_BLOCKED")
        if calc.dec(robot["max_speed_cm_s"]) > calc.dec(zone["ordinance_max_speed_cm_s"]):
            raise ApiError("ERR_ORDINANCE_SPEED_EXCEEDED")
        robot["duty_state"] = "STAGING"
        bump(robot)
    elif action == "MAKE_AVAILABLE":
        if duty not in ("STAGING", "CHARGING", "MAINTENANCE"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if robot["health_state"] not in ("NOMINAL", "DEGRADED"):
            raise ApiError("ERR_ROBOT_HEALTH_BLOCKED")
        if calc.dec(robot["battery_pct"]) < calc.MIN_BATTERY_PCT:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The robot's battery is below the minimum dispatch charge.",
            )
        robot["duty_state"] = "AVAILABLE"
        held = robot.get("current_bay_reservation_id")
        if duty == "CHARGING" or (duty == "MAINTENANCE" and held is not None):
            reservation = db.reservations.get(held or "")
            if reservation is not None:
                reservation["state"] = "RELEASED"
                bump(reservation)
                bay = db.bays.get(reservation["bay_id"])
                if bay is not None:
                    cascades.remove_bay_minutes(bay, reservation["window_minutes"])
            robot["current_bay_reservation_id"] = None
        bump(robot)
    elif action in ("BEGIN_CHARGE", "BEGIN_MAINTENANCE"):
        if duty != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        wanted = "CHARGE" if action == "BEGIN_CHARGE" else "SERVICE"
        reservation = _resolve_depot_reservation(robot, reservation_id, wanted)
        robot["duty_state"] = "CHARGING" if action == "BEGIN_CHARGE" else "MAINTENANCE"
        robot["current_bay_reservation_id"] = reservation["id"]
        bump(robot)
    else:  # RETIRE
        if duty not in ("OFFLINE", "STAGING", "AVAILABLE", "CHARGING", "MAINTENANCE"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        robot["duty_state"] = "RETIRED"
        bump(robot)
        live = cascades.by_created(
            [
                r
                for r in db.reservations.values()
                if r["robot_id"] == robot["id"] and r["state"] in ("HELD", "ACTIVE")
            ]
        )
        for reservation in live:
            cascades.cancel_reservation_row(reservation, "CANCELLED")

    return object_response(public(robot))


@bp.post("/robots/<robot_id>/health-transitions")
def health_transition(robot_id):
    authorize(("SafetyOfficer",))
    payload = body()
    action = check_enum(payload, "action", HEALTH_ACTIONS)
    check_str(payload, "reason", 1, None, required=False)

    robot = must("robots", robot_id)
    health = robot["health_state"]

    if action == "DOWNGRADE":
        if health != "NOMINAL":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        robot["health_state"] = "DEGRADED"
        bump(robot)
    elif action == "IMPAIR":
        if health != "DEGRADED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        robot["health_state"] = "IMPAIRED"
        bump(robot)
    elif action == "QUARANTINE":
        if health not in ("NOMINAL", "DEGRADED", "IMPAIRED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        cascades.quarantine_robot(robot, tamper=False)
    else:  # CLEAR
        if health == "QUARANTINED":
            if robot["duty_state"] == "ON_MISSION":
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "A robot on mission cannot have its quarantine cleared.",
                )
            for incident in db.incidents.values():
                if incident["robot_id"] == robot["id"] and incident["report_state"] == "DRAFT":
                    raise ApiError("ERR_MANDATORY_INCIDENT_UNFILED")
            robot["health_state"] = "NOMINAL"
            robot["tamper_flag"] = False
            bump(robot)
        elif health == "IMPAIRED":
            robot["health_state"] = "DEGRADED"
            bump(robot)
        else:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    return object_response(public(robot))


@bp.post("/robots/<robot_id>/telemetry")
def telemetry(robot_id):
    authorize(("FleetDispatcher", "RemoteOperator"))
    payload = body()
    battery_pct = check_number(payload, "battery_pct", ge=0, le=100, required=False)
    odometer_delta_m = check_number(payload, "odometer_delta_m", required=False)
    yield_event_delta = check_int(payload, "yield_event_delta", required=False)
    tamper_flag = check_bool(payload, "tamper_flag", required=False)

    robot = must("robots", robot_id)

    if battery_pct is not None:
        robot["battery_pct"] = battery_pct
    if odometer_delta_m is not None:
        robot["odometer_m"] = float(calc.dec(robot["odometer_m"]) + calc.dec(odometer_delta_m))
    if yield_event_delta is not None:
        robot["yield_event_count"] += yield_event_delta
    bump(robot)

    if (
        battery_pct is not None
        and calc.dec(battery_pct) <= calc.LOW_BATTERY_PCT
        and robot["health_state"] == "NOMINAL"
    ):
        robot["health_state"] = "DEGRADED"
        bump(robot)

    if tamper_flag is True:
        cascades.quarantine_robot(robot, tamper=True)

    return object_response(public(robot))
