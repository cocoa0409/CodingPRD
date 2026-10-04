"""Conduct incidents: report, list, adjudication transitions (incl. the
depth-3 board separation cascade)."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_ZERO_TOLERANCE_BOARD_REQUIRED,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_date,
    as_enum,
    as_int,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("conduct", __name__)

INFRACTION_CODES = {"CURFEW_VIOLATION", "THEFT", "VIOLENCE", "DRUGS", "WEAPONS", "OTHER"}
INCIDENT_ACTIONS = [
    "begin_investigation",
    "dismiss",
    "sanction",
    "refer_board",
    "exonerate",
    "separate",
]
INCIDENT_TERMINAL = {"DISMISSED", "SANCTIONED", "EXONERATED", "SEPARATION_ORDERED"}


@bp.route("/jc/conduct-incidents", methods=["POST"])
def create_incident():
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor"})
    body = get_body()
    check_unknown(body, {"enrollment_id", "infraction_code", "occurred_at", "note"})
    enrollment_id = as_str(body, "enrollment_id", required=True)
    infraction_code = as_enum(body, "infraction_code", sorted(INFRACTION_CODES), required=True)
    occurred_at = as_date(body, "occurred_at", required=True)
    note = as_str(body, "note")
    if enrollment_id not in STORE.enrollments:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    rec = new_record()
    rec.update(
        {
            "enrollment_id": enrollment_id,
            "infraction_code": infraction_code,
            "zero_tolerance": infraction_code in domain.ZERO_TOLERANCE_CODES,
            "sanction_points": None,
            "occurred_at": occurred_at,
            "note": note,
            "status": "REPORTED",
        }
    )
    STORE.conduct_incidents[rec["id"]] = rec
    return ok_object(serializers.incident_view(rec), status=201)


@bp.route("/jc/enrollments/<enrollment_id>/conduct-incidents", methods=["GET"])
def list_enrollment_incidents(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor", "EnrollmentManager"})
    if enrollment_id not in STORE.enrollments:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    limit, offset = pagination_params()
    items = [
        i for i in STORE.conduct_incidents.values() if i["enrollment_id"] == enrollment_id
    ]
    items.sort(key=lambda i: i["_seq"])
    page, meta = paginate([serializers.incident_view(i) for i in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/conduct-incidents/<incident_id>/transition", methods=["POST"])
def incident_transition(incident_id):
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor"})
    incident = STORE.conduct_incidents.get(incident_id)
    if incident is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Conduct incident not found")
    body = get_body()
    check_unknown(body, {"action", "sanction_points", "note"})
    action = as_enum(body, "action", INCIDENT_ACTIONS, required=True)
    sanction_points = None
    if "sanction_points" in body:
        sanction_points = as_int(
            body,
            "sanction_points",
            lo=domain.SANCTION_POINTS_MIN,
            hi=domain.SANCTION_POINTS_MAX,
        )
    note = as_str(body, "note")
    if action == "sanction" and sanction_points is None:
        from errors import ERR_INVALID_REQUEST

        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "sanction_points is required for the sanction action",
        )
    # Priority 7: terminal lockdown.
    if incident["status"] in INCIDENT_TERMINAL:
        raise ApiError(
            ERR_ALREADY_TERMINAL[0],
            ERR_ALREADY_TERMINAL[1],
            "Conduct incident is terminal",
        )
    status = incident["status"]
    if action == "begin_investigation":
        if status != "REPORTED":
            _invalid_state(action, status)
        incident["status"] = "INVESTIGATING"
    elif action == "dismiss":
        if status != "INVESTIGATING":
            _invalid_state(action, status)
        incident["status"] = "DISMISSED"
        if note is not None:
            incident["note"] = note
    elif action == "sanction":
        if status != "INVESTIGATING":
            _invalid_state(action, status)
        # Priority 10: zero-tolerance incidents may only be resolved by the board.
        if incident["zero_tolerance"]:
            raise ApiError(
                ERR_ZERO_TOLERANCE_BOARD_REQUIRED[0],
                ERR_ZERO_TOLERANCE_BOARD_REQUIRED[1],
                "Zero-tolerance incidents must be referred to the board",
            )
        incident["status"] = "SANCTIONED"
        incident["sanction_points"] = sanction_points
    elif action == "refer_board":
        if status != "INVESTIGATING":
            _invalid_state(action, status)
        incident["status"] = "BOARD_REVIEW"
    elif action == "exonerate":
        if status != "BOARD_REVIEW":
            _invalid_state(action, status)
        incident["status"] = "EXONERATED"
    elif action == "separate":
        if status != "BOARD_REVIEW":
            _invalid_state(action, status)
        incident["status"] = "SEPARATION_ORDERED"
        # Depth-3 cascade: incident decision -> enrollment -> dormitory ->
        # center occupancy; transition plan starts with all tracks PENDING
        # (no hire inheritance on a board-ordered separation, PRD 3.4).
        enrollment = STORE.enrollments[incident["enrollment_id"]]
        if enrollment["training_status"] not in domain.TRAINING_TERMINAL:
            domain.finalize_enrollment_terminal(
                enrollment, "SEPARATED", "CONDUCT_BOARD", True, False
            )
    bump(incident)
    domain.recompute_conduct_hold(incident["enrollment_id"])
    return ok_object(serializers.incident_view(incident), status=200)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
