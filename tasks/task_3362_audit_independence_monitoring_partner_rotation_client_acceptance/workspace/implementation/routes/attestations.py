"""Affiliate independence attestations for multinational engagements."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, store
from core.errors import (
    ERR_ATTESTATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ApiError,
)
from core.response import send
from core.serialize import serialize
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response
from services.attestations import apply_attestation_action, create_attestation_row

bp = Blueprint("attestations", __name__)

CREATE_FIELDS = ("affiliate_id", "engagement_id", "breach_count")
ACTIONS = ("ATTEST", "WAIVE", "REPORT_BREACH", "RESET_ATTESTATION")


@bp.route("/affiliate-attestations", methods=["POST"])
def create_attestation():
    payload = body(CREATE_FIELDS)
    affiliate_id = V.string(payload, "affiliate_id", required=True)
    engagement_id = V.string(payload, "engagement_id", required=True)
    breach_count = V.integer(payload, "breach_count", default=0, minimum=0)
    require_role([C.ROLE_PLATFORM_ADMIN])
    if store.affiliates.get(affiliate_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "affiliate_id does not resolve to an existing affiliate.")
    if store.engagements.get(engagement_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "engagement_id does not resolve to an existing engagement.")
    row = create_attestation_row(affiliate_id, engagement_id, breach_count)
    return send(serialize("attestation", row), 201)


@bp.route("/affiliate-attestations", methods=["GET"])
def list_attestations():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("attestations"), {
        "affiliate_id": "affiliate_id",
        "engagement_id": "engagement_id",
        "attestation_status": "attestation_status",
    })
    return list_response(rows, lambda row: serialize("attestation", row))


@bp.route("/affiliate-attestations/<attestation_id>", methods=["GET"])
def get_attestation(attestation_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("attestations", attestation_id, ERR_ATTESTATION_NOT_FOUND)
    return send(serialize("attestation", row))


@bp.route("/affiliate-attestations/<attestation_id>/transitions", methods=["POST"])
def transition_attestation(attestation_id):
    payload = body(("action",))
    action = V.string(payload, "action", required=True)
    if action not in ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown action '%s'." % action)
    require_role([C.ROLE_INDEPENDENCE_OFFICER])
    row = fetch("attestations", attestation_id, ERR_ATTESTATION_NOT_FOUND)
    apply_attestation_action(row, action)
    return send(serialize("attestation", row))
