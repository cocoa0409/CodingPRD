"""EvidenceDocument endpoints (PRD 3.8): upload, list, get, verify, reject.

Segregation of duties: the uploader may not verify or reject. Rejecting a
VERIFIED origin cert or labor record fires the recompute -> challenge ->
audit cascade; rejecting a merely-SUBMITTED document has no downstream effect.
"""
from flask import Blueprint, request

import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_enum, req_date

bp = Blueprint("evidence", __name__)


def get_doc(did):
    d = DB["docs"].get(did)
    if d is None:
        raise ApiError("ERR_DOC_NOT_FOUND", "evidence document id does not resolve")
    return d


@bp.post("/footwear/evidence-documents")
@require_roles("SourcingManager", "ComplianceOfficer")
def create_doc(_uid, _role):
    b = body()
    claim_id = b.get("claim_id")
    lot_id = b.get("material_lot_id")
    run_id = b.get("production_run_id")
    # Family 4 (existence) precedes family 5 (schema / link ambiguity).
    if claim_id is not None and claim_id not in DB["claims"]:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim id does not resolve")
    if lot_id is not None and lot_id not in DB["lots"]:
        raise ApiError("ERR_LOT_NOT_FOUND", "material lot id does not resolve")
    if run_id is not None and run_id not in DB["runs"]:
        raise ApiError("ERR_RUN_NOT_FOUND", "production run id does not resolve")
    dtype = req_enum(b, "doc_type", constants.DOC_TYPES)
    issuer = req_str(b, "issuer")
    vf = req_date(b, "valid_from")
    vu = req_date(b, "valid_until")
    if vu <= vf:
        raise ApiError("ERR_INVALID_REQUEST", "valid_until must be strictly after valid_from")
    links = [x for x in (claim_id, lot_id, run_id) if x is not None]
    if len(links) != 1:
        raise ApiError(
            "ERR_DOC_LINK_AMBIGUOUS",
            "exactly one of claim_id / material_lot_id / production_run_id must be set",
        )
    d = base_fields()
    d.update({
        "doc_type": dtype,
        "claim_id": claim_id,
        "material_lot_id": lot_id,
        "production_run_id": run_id,
        "issuer": issuer,
        "valid_from": vf,
        "valid_until": vu,
        "uploaded_by": _uid,
        "status": "SUBMITTED",
    })
    DB["docs"][d["id"]] = d
    return ok_obj(serializers.pub(d), 201)


@bp.get("/footwear/evidence-documents")
@require_roles(*constants.ALL_ROLES)
def list_docs(_uid, _role):
    # Lazy expiry applies whenever documents are read.
    for d in DB["docs"].values():
        cascade.doc_live_verified(d)
    items = sorted_items(DB["docs"])
    claim_id = request.args.get("claim_id")
    lot_id = request.args.get("material_lot_id")
    run_id = request.args.get("production_run_id")
    dtype = request.args.get("doc_type")
    status = request.args.get("status")
    if claim_id is not None:
        items = [d for d in items if d["claim_id"] == claim_id]
    if lot_id is not None:
        items = [d for d in items if d["material_lot_id"] == lot_id]
    if run_id is not None:
        items = [d for d in items if d["production_run_id"] == run_id]
    if dtype is not None:
        items = [d for d in items if d["doc_type"] == dtype]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response([serializers.pub(d) for d in items])


@bp.get("/footwear/evidence-documents/<did>")
@require_roles(*constants.ALL_ROLES)
def get_one_doc(did, _uid, _role):
    d = get_doc(did)
    cascade.doc_live_verified(d)
    return ok_obj(serializers.pub(d))


def _segregation_guard(doc, uid):
    """Family 3: nobody may verify or reject a document they uploaded."""
    if doc["uploaded_by"] == uid:
        raise ApiError(
            "ERR_SELF_ATTESTATION_FORBIDDEN",
            "the document's uploader may not verify or reject it",
        )


@bp.post("/footwear/evidence-documents/<did>/verify")
@require_roles("ComplianceOfficer")
def verify_doc(did, _uid, _role):
    doc = get_doc(did)
    cascade.doc_live_verified(doc)
    _segregation_guard(doc, _uid)
    if doc["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "only a SUBMITTED document can be verified")
    doc["status"] = "VERIFIED"
    touch(doc)
    return ok_obj(serializers.pub(doc))


@bp.post("/footwear/evidence-documents/<did>/reject")
@require_roles("ComplianceOfficer")
def reject_doc(did, _uid, _role):
    doc = get_doc(did)
    cascade.doc_live_verified(doc)
    _segregation_guard(doc, _uid)
    if doc["status"] not in ("SUBMITTED", "VERIFIED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a SUBMITTED or VERIFIED document can be rejected",
        )
    was_verified = doc["status"] == "VERIFIED"
    doc["status"] = "REJECTED"
    touch(doc)
    if was_verified:
        # Only VERIFIED -> REJECTED fires the recompute/challenge/audit cascade.
        cascade.cascade_doc_rejected_verified(doc)
    return ok_obj(serializers.pub(doc))
