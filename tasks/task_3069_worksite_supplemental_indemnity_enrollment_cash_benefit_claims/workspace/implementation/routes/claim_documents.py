"""Claim document endpoints."""
from flask import Blueprint

import db
import errors as E
from middleware import require_role
from response import success_object
from serializers import claim_document
from util import get_body, get_or_404

bp = Blueprint("claim_documents", __name__)

STORE = db.STORES["claim_documents"]

_DOC_TYPES = ("DIAGNOSIS_PROOF", "PROCEDURE_PROOF", "ITEMIZED_BILL", "ATTENDING_PHYSICIAN_STATEMENT")


@bp.route("/claim-documents", methods=["POST"])
def create(role, user_id):
    require_role(role, {"PolicyholderServices", "ClaimsAdjuster"})
    body = get_body(["claim_id", "doc_type", "content_ref"])
    claim = db.STORES["claims"].get(body["claim_id"])
    if claim is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "claim_id does not exist")
    if body["doc_type"] not in _DOC_TYPES:
        raise E.err(E.ERR_INVALID_REQUEST, "doc_type invalid")
    if claim["status"] not in ("UNDER_REVIEW", "APPEALED"):
        raise E.err(E.ERR_INVALID_STATE, "Claim must be UNDER_REVIEW or APPEALED to attach documents")
    rec = db.stamp_created({
        "claim_id": claim["id"],
        "doc_type": body["doc_type"],
        "content_ref": body["content_ref"],
        "status": "RECEIVED",
    })
    STORE[rec["id"]] = rec
    return success_object(claim_document(rec), status=201)


@bp.route("/claim-documents/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    return success_object(claim_document(rec))


def _transition(rid, target):
    rec = get_or_404(STORE, rid)
    if rec["status"] != "RECEIVED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot transition document from {rec['status']}")
    claim = db.STORES["claims"][rec["claim_id"]]
    if claim["status"] not in ("UNDER_REVIEW", "APPEALED"):
        raise E.err(E.ERR_INVALID_STATE, "Claim must be UNDER_REVIEW or APPEALED")
    rec["status"] = target
    db.touch(rec)
    return success_object(claim_document(rec))


@bp.route("/claim-documents/<rid>/accept", methods=["POST"])
def accept(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    return _transition(rid, "ACCEPTED")


@bp.route("/claim-documents/<rid>/reject", methods=["POST"])
def reject(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    return _transition(rid, "REJECTED")
