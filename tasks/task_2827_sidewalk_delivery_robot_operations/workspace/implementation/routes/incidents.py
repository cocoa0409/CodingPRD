"""Incident reporting: the branching municipal / insurer workflow."""

from flask import Blueprint

import cascades
from common import must, serve_list
from db import bump, db, public
from errors import ApiError, bad
from middleware import (
    action_role,
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

bp = Blueprint("incidents", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "FleetDispatcher",
    "RemoteOperator",
    "SafetyOfficer",
    "CustomerSupport",
)
FILE_ROLES = ("RemoteOperator", "SafetyOfficer")
TRANSITION_ROLES = ("SafetyOfficer", "PlatformAdmin")
CATEGORIES = (
    "PEDESTRIAN_CONTACT",
    "RIGHT_OF_WAY_VIOLATION",
    "VANDALISM",
    "OBSTRUCTION",
    "CLEARANCE_BREACH",
)
SEVERITIES = ("MINOR", "SERIOUS", "CRITICAL")
REPORT_STATES = ("DRAFT", "SUBMITTED_MUNICIPAL", "INSURER_NOTIFIED", "CLOSED", "REJECTED")
REPORT_ACTIONS = (
    "SUBMIT_MUNICIPAL",
    "NOTIFY_INSURER",
    "CLOSE",
    "RETURN_FOR_DETAIL",
    "REJECT",
)
ACTION_ROLES = {
    "SUBMIT_MUNICIPAL": ("SafetyOfficer",),
    "NOTIFY_INSURER": ("SafetyOfficer",),
    "CLOSE": ("SafetyOfficer",),
    "RETURN_FOR_DETAIL": ("SafetyOfficer",),
    "REJECT": ("PlatformAdmin",),
}


@bp.get("/incident-reports")
def list_reports():
    authorize(READ_ROLES)
    limit, offset = pagination()
    zone_id = arg_str("zone_id")
    mission_id = arg_str("mission_id")
    robot_id = arg_str("robot_id")
    report_state = arg_enum("report_state", REPORT_STATES)
    severity = arg_enum("severity", SEVERITIES)
    category = arg_enum("category", CATEGORIES)
    rows = []
    for report in db.incidents.values():
        if zone_id is not None and report["zone_id"] != zone_id:
            continue
        if mission_id is not None and report["mission_id"] != mission_id:
            continue
        if robot_id is not None and report["robot_id"] != robot_id:
            continue
        if report_state is not None and report["report_state"] != report_state:
            continue
        if severity is not None and report["severity"] != severity:
            continue
        if category is not None and report["category"] != category:
            continue
        rows.append(report)
    return serve_list(rows, limit, offset)


@bp.get("/incident-reports/<report_id>")
def get_report(report_id):
    authorize(READ_ROLES)
    return object_response(public(must("incidents", report_id)))


@bp.post("/incident-reports")
def create_report():
    user_id, role = authorize(FILE_ROLES)
    payload = body()
    for name in ("zone_id", "robot_id", "category", "severity", "narrative"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    category = check_enum(payload, "category", CATEGORIES)
    severity = check_enum(payload, "severity", SEVERITIES)
    zone_id = check_str(payload, "zone_id", 1, None)
    robot_id = check_str(payload, "robot_id", 1, None)
    narrative = check_str(payload, "narrative", 1, 2000)
    damage = check_int(payload, "estimated_damage_cents", ge=0, required=False, default=0)
    mission_id = payload.get("mission_id")
    if mission_id is not None and (not isinstance(mission_id, str) or mission_id == ""):
        raise bad("Field 'mission_id' must be a mission identifier when supplied.")

    zone = must("zones", zone_id)
    robot = must("robots", robot_id)
    mission = None
    if mission_id is not None:
        mission = must("missions", mission_id)

    report = cascades.create_incident_row(
        zone_id=zone["id"],
        robot_id=robot["id"],
        mission_id=mission["id"] if mission is not None else None,
        category=category,
        severity=severity,
        narrative=narrative,
        estimated_damage_cents=damage,
        filed_by_user_id=user_id,
        zone=zone,
    )
    zone["open_incident_count"] += 1
    bump(zone)
    return object_response(public(report), 201)


def _close_zone_counter(report):
    zone = db.zones.get(report["zone_id"])
    if zone is not None:
        zone["open_incident_count"] -= 1
        if zone["open_incident_count"] < 0:
            zone["open_incident_count"] = 0
        bump(zone)


@bp.post("/incident-reports/<report_id>/transitions")
def report_transition(report_id):
    user_id, role = authorize(TRANSITION_ROLES)
    payload = body()
    action = check_enum(payload, "action", REPORT_ACTIONS)
    action_role(role, action, ACTION_ROLES)
    municipal_case_ref = None
    insurer_claim_ref = None
    if action == "SUBMIT_MUNICIPAL":
        municipal_case_ref = check_str(payload, "municipal_case_ref", 1, None)
    elif action == "NOTIFY_INSURER":
        insurer_claim_ref = check_str(payload, "insurer_claim_ref", 1, None)

    report = must("incidents", report_id)
    state = report["report_state"]

    if action == "SUBMIT_MUNICIPAL" and user_id == report["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if action == "RETURN_FOR_DETAIL" and user_id != report["reviewed_by_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if action == "SUBMIT_MUNICIPAL":
        if state != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        report["report_state"] = "SUBMITTED_MUNICIPAL"
        report["municipal_case_ref"] = municipal_case_ref
        report["reviewed_by_user_id"] = user_id
        bump(report)
    elif action == "NOTIFY_INSURER":
        if state != "SUBMITTED_MUNICIPAL":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if report["insurer_notification_required"] is not True:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "This report sits below the insurer notification gate.",
            )
        report["report_state"] = "INSURER_NOTIFIED"
        report["insurer_claim_ref"] = insurer_claim_ref
        bump(report)
    elif action == "CLOSE":
        if state not in ("SUBMITTED_MUNICIPAL", "INSURER_NOTIFIED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if state == "SUBMITTED_MUNICIPAL" and report["insurer_notification_required"] is True:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The insurer must be notified before this report can be closed.",
            )
        report["report_state"] = "CLOSED"
        bump(report)
        _close_zone_counter(report)
    elif action == "RETURN_FOR_DETAIL":
        if state != "SUBMITTED_MUNICIPAL":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        report["report_state"] = "DRAFT"
        report["municipal_case_ref"] = None
        report["reviewed_by_user_id"] = None
        bump(report)
    else:  # REJECT
        if state != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if report["severity"] != "MINOR":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only a MINOR incident report may be rejected.",
            )
        report["report_state"] = "REJECTED"
        bump(report)
        _close_zone_counter(report)

    return object_response(public(report))
