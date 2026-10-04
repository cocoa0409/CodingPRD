"""Non-audit services and their audit-committee pre-approval lifecycle."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_SERVICE_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.naf import apply_service_action, create_service_row

bp = Blueprint("naf", __name__)

CREATE_FIELDS = ("client_id", "engagement_id", "service_category", "fee_cents",
                 "committee_resolution_ref", "approval_expires_on")
TRANSITION_FIELDS = ("action", "committee_resolution_ref")
ACTIONS = ("SUBMIT_FOR_APPROVAL", "APPROVE", "REJECT", "RETURN_TO_DRAFT", "REVOKE")


@bp.route("/non-audit-services", methods=["POST"])
def create_service():
    payload = body(CREATE_FIELDS)
    client_id = V.string(payload, "client_id", required=True)
    engagement_id = V.string(payload, "engagement_id", default=None, nullable=True)
    category = V.enum(payload, "service_category", C.SERVICE_CATEGORIES, required=True)
    fee_cents = V.number(payload, "fee_cents", required=True, minimum=0)
    resolution_ref = V.string(payload, "committee_resolution_ref", default=None, nullable=True)
    expires_on = V.datetime_field(payload, "approval_expires_on", default=None, nullable=True)
    require_role([C.ROLE_AUDIT_COMMITTEE_LIAISON])
    if store.clients.get(client_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "client_id does not resolve to an existing client.")
    if engagement_id is not None and store.engagements.get(engagement_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    row = create_service_row(client_id, engagement_id, category, fee_cents,
                             resolution_ref, expires_on)
    return send(serialize("service", row), 201)


@bp.route("/non-audit-services", methods=["GET"])
def list_services():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("services"), {
        "client_id": "client_id",
        "engagement_id": "engagement_id",
        "status": "status",
        "service_category": "service_category",
    })
    return list_response(rows, lambda row: serialize("service", row))


@bp.route("/non-audit-services/<service_id>", methods=["GET"])
def get_service(service_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("services", service_id, ERR_SERVICE_NOT_FOUND)
    return send(serialize("service", row))


@bp.route("/non-audit-services/<service_id>/transitions", methods=["POST"])
def transition_service(service_id):
    payload = body(TRANSITION_FIELDS)
    action = V.string(payload, "action", required=True)
    if action not in ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    role, _user_id = require_role([C.ROLE_AUDIT_COMMITTEE_LIAISON, C.ROLE_INDEPENDENCE_OFFICER])
    if action == "REVOKE" and role != C.ROLE_INDEPENDENCE_OFFICER:
        raise ApiError(ERR_UNAUTHORIZED_ROLE,
                       "Only the IndependenceOfficer may revoke an approved service.")
    row = fetch("services", service_id, ERR_SERVICE_NOT_FOUND)
    apply_service_action(row, action, payload)
    return send(serialize("service", row))
