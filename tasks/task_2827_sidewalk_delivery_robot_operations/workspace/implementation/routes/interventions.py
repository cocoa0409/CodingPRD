"""Remote takeover events running alongside a mission."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now_iso, public
from errors import ApiError, bad
from middleware import (
    action_role,
    arg_bool,
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

bp = Blueprint("interventions", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "RemoteOperator", "SafetyOfficer")
CREATE_ROLES = ("RemoteOperator", "FleetDispatcher")
TRANSITION_ROLES = ("RemoteOperator", "SafetyOfficer", "FleetDispatcher")
TRIGGER_REASONS = (
    "LOW_CONFIDENCE",
    "PEDESTRIAN_CONFLICT",
    "OBSTACLE",
    "CROSSING_ASSIST",
    "VANDALISM_ALERT",
)
TAKEOVER_STATES = ("REQUESTED", "ACKNOWLEDGED", "ACTIVE", "RELEASED", "ESCALATED")
EVENT_ACTIONS = ("ACKNOWLEDGE", "ASSUME", "ESCALATE", "DEESCALATE", "RELEASE")
ACTION_ROLES = {
    "ACKNOWLEDGE": ("RemoteOperator",),
    "ASSUME": ("RemoteOperator",),
    "ESCALATE": ("RemoteOperator",),
    "DEESCALATE": ("SafetyOfficer",),
    "RELEASE": ("RemoteOperator", "SafetyOfficer", "FleetDispatcher"),
}
MISSION_TERMINAL = ("COMPLETED", "ABORTED")


@bp.get("/intervention-events")
def list_events():
    authorize(READ_ROLES)
    limit, offset = pagination()
    mission_id = arg_str("mission_id")
    takeover_state = arg_enum("takeover_state", TAKEOVER_STATES)
    trigger_reason = arg_enum("trigger_reason", TRIGGER_REASONS)
    mandatory = arg_bool("mandatory")
    rows = []
    for event in db.interventions.values():
        if mission_id is not None and event["mission_id"] != mission_id:
            continue
        if takeover_state is not None and event["takeover_state"] != takeover_state:
            continue
        if trigger_reason is not None and event["trigger_reason"] != trigger_reason:
            continue
        if mandatory is not None and event["mandatory"] != mandatory:
            continue
        rows.append(event)
    return serve_list(rows, limit, offset)


@bp.get("/intervention-events/<event_id>")
def get_event(event_id):
    authorize(READ_ROLES)
    return object_response(public(must("interventions", event_id)))


@bp.post("/intervention-events")
def create_event():
    authorize(CREATE_ROLES)
    payload = body()
    for name in ("mission_id", "trigger_reason", "autonomy_confidence_pct"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    trigger_reason = check_enum(payload, "trigger_reason", TRIGGER_REASONS)
    mission_id = check_str(payload, "mission_id", 1, None)
    confidence = check_int(payload, "autonomy_confidence_pct", ge=0, le=100)

    mission = must("missions", mission_id)
    if mission["mission_state"] in MISSION_TERMINAL:
        raise ApiError("ERR_MISSION_ALREADY_TERMINAL")

    robot = db.robots.get(mission["robot_id"])
    zone = db.zones.get(robot["zone_id"]) if robot is not None else None

    event = create_row(
        db.interventions,
        {
            "mission_id": mission["id"],
            "trigger_reason": trigger_reason,
            "autonomy_confidence_pct": confidence,
            "takeover_state": "REQUESTED",
            "mandatory": calc.takeover_mandatory(confidence, zone),
            "operator_user_id": None,
            "control_seconds": 0,
            "assumed_at_utc": None,
            "escalation_reason": None,
        },
    )
    return object_response(public(event), 201)


@bp.post("/intervention-events/<event_id>/transitions")
def event_transition(event_id):
    user_id, role = authorize(TRANSITION_ROLES)
    payload = body()
    action = check_enum(payload, "action", EVENT_ACTIONS)
    action_role(role, action, ACTION_ROLES)
    escalation_reason = None
    if action == "ESCALATE":
        escalation_reason = check_str(payload, "escalation_reason", 1, None)

    event = must("interventions", event_id)
    mission = db.missions.get(event["mission_id"])
    state = event["takeover_state"]

    if action == "ESCALATE" and user_id != event["operator_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if action == "RELEASE" and role == "RemoteOperator":
        if user_id != event["operator_user_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if action == "ACKNOWLEDGE":
        if state != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["takeover_state"] = "ACKNOWLEDGED"
        bump(event)
    elif action == "ASSUME":
        if state != "ACKNOWLEDGED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if mission is None or mission["mission_state"] not in ("EN_ROUTE", "BLOCKED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Control can only be assumed on a mission that is EN_ROUTE or BLOCKED.",
            )
        event["takeover_state"] = "ACTIVE"
        event["assumed_at_utc"] = now_iso()
        event["operator_user_id"] = user_id
        bump(event)
    elif action == "ESCALATE":
        if state != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["takeover_state"] = "ESCALATED"
        event["escalation_reason"] = escalation_reason
        bump(event)
        if mission is not None:
            mission["escalation_count"] += 1
            bump(mission)
    elif action == "DEESCALATE":
        if state != "ESCALATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["takeover_state"] = "ACTIVE"
        bump(event)
    else:  # RELEASE
        if state not in ("REQUESTED", "ACTIVE", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if state == "REQUESTED" and event["mandatory"] is True:
            raise ApiError("ERR_TAKEOVER_REQUIRED")
        if event["assumed_at_utc"] is None:
            event["control_seconds"] = 0
        else:
            event["control_seconds"] = cascades.whole_seconds_between(
                event["assumed_at_utc"], now_iso()
            )
        event["takeover_state"] = "RELEASED"
        bump(event)
        if mission is not None:
            mission["intervention_count"] += 1
            bump(mission)

    return object_response(public(event))
