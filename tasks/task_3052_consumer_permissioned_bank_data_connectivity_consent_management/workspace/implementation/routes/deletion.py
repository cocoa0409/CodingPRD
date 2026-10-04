"""Data deletion requests: create, list, get, ack."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_ACTIVE, ERR_ACK_NOT_REQUIRED, ERR_UNAUTHORIZED,
)
from services import core
from services.serializers import deletion_request_out

bp = Blueprint("deletion", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient")


def _get_request(request_id):
    dr = db.deletion_requests.get(request_id)
    if dr is None:
        raise err(ERR_NOT_FOUND, "DataDeletionRequest not found")
    return dr


@bp.route("/consents/<consentId>/deletion_requests", methods=["POST"])
def create_deletion_request(consentId):
    user_id, role = require_role("Consumer")
    consent = db.consents.get(consentId)
    if consent is None:
        raise err(ERR_NOT_FOUND, "ConsentRecord not found")
    core.lazy_expire(consent)

    # ownership
    if consent["consumer_ref"] != user_id:
        raise err(ERR_UNAUTHORIZED, "X-User-ID must equal consent consumer_ref")

    # state (5): consent in {ACTIVE, REVOKED, EXPIRED}
    if consent["status"] not in ("ACTIVE", "REVOKED", "EXPIRED"):
        raise err(ERR_INVALID_STATE,
                  "Consent must be ACTIVE, REVOKED, or EXPIRED for deletion request")

    # uniqueness (17): no other non-COMPLETED request for this consent
    for dr in db.deletion_requests.values():
        if dr["consent_id"] == consent["id"] and dr["status"] != "COMPLETED":
            raise err(ERR_DUPLICATE_ACTIVE,
                      "A non-COMPLETED deletion request already exists for this consent")

    dr = {
        "consent_id": consent["id"],
        "status": "PROPAGATING",  # PENDING -> PROPAGATING immediately
        "requested_at": db.now_iso(),
        "completed_at": None,
        "acked_recipient_ids": [],
        "_required_recipients": [consent["recipient_id"]],
    }
    core.stamp_new(dr)
    db.deletion_requests[dr["id"]] = dr

    # DATA_DELETED webhook to the consent's recipient (one per request; use the
    # first connection as the carrier if any exist, else synthesize a row with
    # connection_id of any connection under this consent)
    carrier_conn = None
    for conn in db.connections.values():
        if conn["consent_id"] == consent["id"]:
            carrier_conn = conn
            break
    conn_id = carrier_conn["id"] if carrier_conn else None
    ev = core.emit_webhook(conn_id, consent["recipient_id"], "DATA_DELETED",
                           {"consent_id": consent["id"],
                            "deletion_request_id": dr["id"]})
    dr["_data_deleted_webhook_id"] = ev["id"]

    # if consent still ACTIVE: revoke with full cascade
    if consent["status"] == "ACTIVE":
        core.revoke_consent_cascade(consent, write_audit=False)

    return success_object(deletion_request_out(dr), 201)


@bp.route("/consents/<consentId>/deletion_requests", methods=["GET"])
def list_consent_deletion_requests(consentId):
    require_role(*ALL_READ_ROLES)
    consent = db.consents.get(consentId)
    if consent is None:
        raise err(ERR_NOT_FOUND, "ConsentRecord not found")
    limit, offset = parse_limit_offset(request.args)
    items = [dr for dr in db.deletion_requests.values() if dr["consent_id"] == consent["id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([deletion_request_out(dr) for dr in page], limit, offset, total)


@bp.route("/deletion_requests/<requestId>", methods=["GET"])
def get_deletion_request(requestId):
    require_role(*ALL_READ_ROLES)
    dr = _get_request(requestId)
    return success_object(deletion_request_out(dr))


@bp.route("/deletion_requests/<requestId>/ack", methods=["POST"])
def ack_deletion_request(requestId):
    user_id, role = require_role("Recipient")
    dr = _get_request(requestId)

    # state (5)
    if dr["status"] != "PROPAGATING":
        raise err(ERR_INVALID_STATE, "Deletion request is not PROPAGATING")

    # ack integrity (19)
    if user_id not in dr["_required_recipients"] or user_id in dr["acked_recipient_ids"]:
        raise err(ERR_ACK_NOT_REQUIRED,
                  "Acknowledging recipient is not a required ack target or already acked")

    dr["acked_recipient_ids"].append(user_id)

    remaining = set(dr["_required_recipients"]) - set(dr["acked_recipient_ids"])
    if not remaining:
        dr["status"] = "COMPLETED"  # ACKED_BY_ALL -> COMPLETED immediately
        dr["completed_at"] = db.now_iso()
        core.audit(role, "deletion.completed", "DataDeletionRequest", dr["id"],
                   {"consent_id": dr["consent_id"]})
    core.touch(dr)
    return success_object(deletion_request_out(dr))
