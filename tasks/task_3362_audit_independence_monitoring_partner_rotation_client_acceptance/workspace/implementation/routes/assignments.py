"""Engagement role assignments: staffing, reads and the end action."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_PROFESSIONAL_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.assignments import create_assignment_row, end_assignment_row
from services.independence import refresh_all_assignments, sweep_cooling_off

bp = Blueprint("assignments", __name__)

CREATE_FIELDS = ("engagement_id", "professional_id", "role", "started_on",
                 "scheduled_end_on", "expected_engagement_version")


@bp.route("/role-assignments", methods=["POST"])
def create_assignment():
    payload = body(CREATE_FIELDS)
    engagement_id = V.string(payload, "engagement_id", required=True)
    professional_id = V.string(payload, "professional_id", required=True)
    role = V.enum(payload, "role", C.ASSIGNMENT_ROLES, required=True)
    started_on = V.datetime_field(payload, "started_on", required=True)
    scheduled_end_on = V.datetime_field(payload, "scheduled_end_on", required=True)
    expected_version = V.integer(payload, "expected_engagement_version", required=True)
    require_role([C.ROLE_ENGAGEMENT_PARTNER])
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    professional = store.professionals.get(professional_id)
    if professional is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "professional_id does not resolve to an existing professional.")
    sweep_cooling_off()
    row = create_assignment_row(engagement, professional, role, started_on,
                                scheduled_end_on, expected_version)
    return send(serialize("assignment", row), 201)


@bp.route("/role-assignments", methods=["GET"])
def list_assignments():
    require_role(C.READ_ALL_ROLES)
    sweep_cooling_off()
    refresh_all_assignments()
    rows = filter_rows(all_rows("assignments"), {
        "engagement_id": "engagement_id",
        "professional_id": "professional_id",
        "role": "role",
        "status": "status",
        "rotation_status": "rotation_status",
    })
    return list_response(rows, lambda row: serialize("assignment", row))


@bp.route("/role-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("assignments", assignment_id, ERR_ASSIGNMENT_NOT_FOUND)
    sweep_cooling_off()
    refresh_all_assignments()
    return send(serialize("assignment", row))


@bp.route("/role-assignments/<assignment_id>/end", methods=["POST"])
def end_assignment(assignment_id):
    body(())
    require_role([C.ROLE_ENGAGEMENT_PARTNER])
    row = fetch("assignments", assignment_id, ERR_ASSIGNMENT_NOT_FOUND)
    end_assignment_row(row)
    return send(serialize("assignment", row))
