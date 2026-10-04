"""DirectoryEndpoint routes."""

from flask import Blueprint, request

import db
import serializers
from clock import ok
from request_context import (
    actor,
    allowed,
    body,
    created_order,
    need_endpoint,
    page_args,
    paginate,
)
from services import certification

bp = Blueprint("directory_endpoints", __name__)

ALL_ROLES = [
    "NetworkOperator", "ParticipantAdmin", "Prescriber",
    "Pharmacy", "HubOperator", "PatientService",
]


@bp.get("/network/directory-endpoints")
def list_endpoints():
    role, _ = actor()
    allowed(role, ALL_ROLES)
    limit, offset = page_args()
    rows = db.all_rows("endpoints")
    for field in ("participant_id", "service_set", "endpoint_role", "message_standard"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.endpoint(e) for e in window], **meta)


@bp.get("/network/directory-endpoints/<eid>")
def get_endpoint(eid):
    role, _ = actor()
    allowed(role, ALL_ROLES)
    endpoint = need_endpoint(eid)
    return ok(serializers.endpoint(endpoint))


@bp.post("/network/directory-endpoints/<eid>/reactivate")
def reactivate(eid):
    role, _ = actor()
    allowed(role, ["ParticipantAdmin"])
    body(required=(), optional=())
    endpoint = need_endpoint(eid)
    certification.reactivate_endpoint(endpoint)
    return ok(serializers.endpoint(endpoint))


@bp.post("/network/directory-endpoints/<eid>/disable")
def disable(eid):
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    body(required=(), optional=())
    endpoint = need_endpoint(eid)
    certification.disable_endpoint(endpoint)
    return ok(serializers.endpoint(endpoint))