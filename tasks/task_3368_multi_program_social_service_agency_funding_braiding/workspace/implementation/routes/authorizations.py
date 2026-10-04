"""Service authorizations: unit blocks drawn against an enrollment."""

from flask import Blueprint, request

import db
from common import resolve_authorization, resolve_enrollment, resolve_grant
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
from services import authorization

bp = Blueprint("authorizations", __name__)

AUTH_ROLES = ("ProgramManager", "FinanceOfficer")


def _filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


@bp.post("/service-authorizations")
def create_authorization():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    payload = body()
    require_fields(payload, ("enrollment_id", "grant_id", "service_code", "authorized_units",
                             "unit_rate_cents", "period_start", "period_end"))
    enrollment = resolve_enrollment(payload["enrollment_id"])
    grant = resolve_grant(payload["grant_id"])
    created = authorization.create(enrollment, grant, payload)
    return object_envelope(db.public(created)), 201


@bp.get("/service-authorizations")
def list_authorizations():
    auth_context()
    require_role(request.headers.get("X-User-Role"), AUTH_ROLES)
    limit, offset = pagination_args()
    matches = _filter(db.ordered("service_authorizations"), "enrollment_id",
                      request.args.get("enrollment_id"))
    matches = _filter(matches, "grant_id", request.args.get("grant_id"))
    matches = _filter(matches, "status", request.args.get("status"))
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/service-authorizations/<authorization_id>")
def read_authorization(authorization_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), AUTH_ROLES)
    found = resolve_authorization(authorization_id)
    return object_envelope(db.public(found))
