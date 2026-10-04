"""Service deliveries: recording, documentation, billing and reversal."""

from flask import Blueprint, request

import db
from common import resolve_authorization, resolve_client, resolve_delivery, resolve_grant
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
from services import allocation, delivery

bp = Blueprint("deliveries", __name__)

READ_ROLES = ("ProgramManager", "FinanceOfficer", "ComplianceOfficer")


def _filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


def _public(delivery_row):
    data = db.public(delivery_row)
    data["alternate_disallowed_cents"] = allocation.alternate_disallowance(delivery_row)
    return data


@bp.post("/service-deliveries")
def create_delivery():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    payload = body()
    require_fields(payload, ("service_authorization_id", "grant_id", "client_id",
                             "units_delivered", "unit_rate_cents"))
    auth = resolve_authorization(payload["service_authorization_id"])
    grant = resolve_grant(payload["grant_id"])
    client = resolve_client(payload["client_id"])
    created = delivery.create(auth, grant, client, payload)
    return object_envelope(_public(created)), 201


@bp.get("/service-deliveries")
def list_deliveries():
    auth_context()
    require_role(request.headers.get("X-User-Role"), READ_ROLES)
    limit, offset = pagination_args()
    matches = _filter(db.ordered("service_deliveries"), "service_authorization_id",
                      request.args.get("service_authorization_id"))
    matches = _filter(matches, "grant_id", request.args.get("grant_id"))
    matches = _filter(matches, "client_id", request.args.get("client_id"))
    matches = _filter(matches, "status", request.args.get("status"))
    rows = [_public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/service-deliveries/<delivery_id>")
def read_delivery(delivery_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), READ_ROLES)
    found = resolve_delivery(delivery_id)
    return object_envelope(_public(found))


@bp.post("/service-deliveries/<delivery_id>/document")
def document_delivery(delivery_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    found = resolve_delivery(delivery_id)
    delivery.document(found)
    return object_envelope(_public(found))


@bp.post("/service-deliveries/<delivery_id>/bill")
def bill_delivery(delivery_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("FinanceOfficer",))
    found = resolve_delivery(delivery_id)
    delivery.bill(found)
    return object_envelope(_public(found))


@bp.post("/service-deliveries/<delivery_id>/void")
def void_delivery(delivery_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("FinanceOfficer",))
    found = resolve_delivery(delivery_id)
    delivery.void(found)
    return object_envelope(_public(found))
