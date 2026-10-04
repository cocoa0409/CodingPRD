"""Enrollments: direct creation, activation, exit and reads."""

from flask import Blueprint, request

import db
from common import resolve_client, resolve_enrollment, resolve_grant, resolve_program
from response import (
    array_envelope,
    auth_context,
    body,
    object_envelope,
    page,
    pagination_args,
    require_fields,
    require_role,
)
from services import enrollment

bp = Blueprint("enrollments", __name__)

MANAGER_ROLES = ("ProgramManager", "FinanceOfficer", "ComplianceOfficer")


def _filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


@bp.post("/enrollments")
def create_enrollment():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    payload = body()
    require_fields(payload, ("client_id", "program_id", "grant_id"))
    client = resolve_client(payload["client_id"])
    program = resolve_program(payload["program_id"])
    grant = resolve_grant(payload["grant_id"])
    created = enrollment.create(client, program, grant)
    return object_envelope(db.public(created)), 201


@bp.get("/enrollments")
def list_enrollments():
    auth_context()
    require_role(request.headers.get("X-User-Role"), MANAGER_ROLES)
    limit, offset = pagination_args()
    matches = _filter(db.ordered("enrollments"), "client_id", request.args.get("client_id"))
    matches = _filter(matches, "program_id", request.args.get("program_id"))
    matches = _filter(matches, "grant_id", request.args.get("grant_id"))
    matches = _filter(matches, "status", request.args.get("status"))
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), MANAGER_ROLES)
    found = resolve_enrollment(enrollment_id)
    return object_envelope(db.public(found))


@bp.post("/enrollments/<enrollment_id>/activate")
def activate_enrollment(enrollment_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    found = resolve_enrollment(enrollment_id)
    enrollment.activate(found)
    return object_envelope(db.public(found))


@bp.post("/enrollments/<enrollment_id>/exit")
def exit_enrollment(enrollment_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    found = resolve_enrollment(enrollment_id)
    enrollment.exit_enrollment(found, body().get("exit_reason"))
    return object_envelope(db.public(found))
