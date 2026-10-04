"""LabelClaim endpoints (PRD 3.8): create, list, get, substantiate, publish,
revoke. Challenge transitions are system-driven and live in cascade.py."""
from flask import Blueprint, request

import calcs
import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items, clock_raw
from validation import body, req_str, req_enum

bp = Blueprint("claims", __name__)


def get_claim(cid):
    c = DB["claims"].get(cid)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "label claim id does not resolve")
    return c


@bp.post("/footwear/label-claims")
@require_roles("ComplianceOfficer")
def create_claim(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    mid = b.get("model_id")
    if mid is not None and mid not in DB["models"]:
        raise ApiError("ERR_MODEL_NOT_FOUND", "model id does not resolve")
    mid = req_str(b, "model_id")
    ctype = req_enum(b, "claim_type", constants.CLAIM_TYPES)
    # Family 9: at most one non-REVOKED claim per (model_id, claim_type).
    if any(c["model_id"] == mid and c["claim_type"] == ctype and c["status"] != "REVOKED"
           for c in DB["claims"].values()):
        raise ApiError(
            "ERR_CLAIM_ALREADY_EXISTS",
            "a non-REVOKED claim already exists for this (model_id, claim_type)",
        )
    c = base_fields()
    c.update({
        "model_id": mid,
        "claim_type": ctype,
        "report_id": None,
        "substantiated_at": None,
        "published_at": None,
        "status": "DRAFT",
        "_evidence_ids": [],
    })
    DB["claims"][c["id"]] = c
    return ok_obj(serializers.pub(c), 201)


@bp.get("/footwear/label-claims")
@require_roles(*constants.ALL_ROLES)
def list_claims(_uid, _role):
    items = sorted_items(DB["claims"])
    mid = request.args.get("model_id")
    rid = request.args.get("report_id")
    ctype = request.args.get("claim_type")
    status = request.args.get("status")
    if mid is not None:
        items = [c for c in items if c["model_id"] == mid]
    if rid is not None:
        items = [c for c in items if c["report_id"] == rid]
    if ctype is not None:
        items = [c for c in items if c["claim_type"] == ctype]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([serializers.pub(c) for c in items])


@bp.get("/footwear/label-claims/<cid>")
@require_roles(*constants.ALL_ROLES)
def get_one_claim(cid, _uid, _role):
    return ok_obj(serializers.pub(get_claim(cid)))


@bp.post("/footwear/label-claims/<cid>/substantiate")
@require_roles("ComplianceOfficer")
def substantiate_claim(cid, _uid, _role):
    claim = get_claim(cid)
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    rid = b.get("report_id")
    if rid is not None and rid not in DB["reports"]:
        raise ApiError("ERR_REPORT_NOT_FOUND", "content report id does not resolve")
    rid = req_str(b, "report_id")
    report = DB["reports"][rid]
    # Family 6 (state): claim state, then report variant, then report status.
    if claim["status"] not in ("DRAFT", "CHALLENGED"):
        raise ApiError("ERR_INVALID_STATE", "claim must be DRAFT or CHALLENGED to substantiate")
    if report["variant"] != "CERTIFIED":
        raise ApiError("ERR_REPORT_NOT_CERTIFIED", "the report must be CERTIFIED")
    if report["status"] != "ACTIVE":
        raise ApiError("ERR_REPORT_NOT_ACTIVE", "the report must be ACTIVE")
    # Family 7 (regulatory), in the pinned order: model match, then threshold.
    run = DB["runs"][report["run_id"]]
    if run["model_id"] != claim["model_id"]:
        raise ApiError(
            "ERR_REPORT_MODEL_MISMATCH",
            "a claim may not be substantiated by another model's report",
        )
    if not calcs.claim_threshold_pass(
        claim["claim_type"], report["us_content_pct"], report["final_assembly_domestic"]
    ):
        raise ApiError(
            "ERR_CONTENT_THRESHOLD_NOT_MET",
            "the report's us_content_pct / final_assembly_domestic does not satisfy the claim type",
        )
    # Family 10 (referential evidence), deliberately after the threshold check.
    certs = cascade.live_verified_claim_docs(claim["id"], "SUPPLIER_ORIGIN_CERT")
    labor = cascade.live_verified_claim_docs(claim["id"], "ASSEMBLY_LABOR_RECORD")
    if not certs or not labor:
        raise ApiError(
            "ERR_REQUIRED_EVIDENCE_MISSING",
            "at least one VERIFIED unexpired SUPPLIER_ORIGIN_CERT and one VERIFIED "
            "unexpired ASSEMBLY_LABOR_RECORD must be attached to the claim",
        )
    claim["report_id"] = report["id"]
    claim["substantiated_at"] = clock_raw()
    if claim["status"] == "CHALLENGED":
        # Re-substantiation closes the PUBLISHED -> CHALLENGED -> SUBSTANTIATED loop.
        claim["published_at"] = None
    claim["status"] = "SUBSTANTIATED"
    # Snapshot the evidence folder counted at substantiation for the publish
    # freshness re-check.
    claim["_evidence_ids"] = [d["id"] for d in certs + labor]
    touch(claim)
    return ok_obj(serializers.pub(claim))


@bp.post("/footwear/label-claims/<cid>/publish")
@require_roles("ComplianceOfficer")
def publish_claim(cid, _uid, _role):
    claim = get_claim(cid)
    if claim["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE", "claim must be SUBSTANTIATED to publish")
    model = DB["models"][claim["model_id"]]
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", "the claim's model must be ACTIVE")
    # Family 8 (temporal): every document counted at substantiation must still
    # be VERIFIED and unexpired at the current logical clock.
    for did in claim["_evidence_ids"]:
        doc = DB["docs"].get(did)
        if doc is None or not cascade.doc_live_verified(doc):
            raise ApiError(
                "ERR_EVIDENCE_STALE",
                "a document counted at substantiation is no longer VERIFIED and unexpired",
            )
    claim["published_at"] = clock_raw()
    claim["status"] = "PUBLISHED"
    touch(claim)
    return ok_obj(serializers.pub(claim))


@bp.post("/footwear/label-claims/<cid>/revoke")
@require_roles("ComplianceOfficer")
def revoke_claim(cid, _uid, _role):
    claim = get_claim(cid)
    # PUBLISHED -> REVOKED is deliberately absent: publish must be challenged first.
    if claim["status"] not in ("DRAFT", "SUBSTANTIATED", "CHALLENGED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only DRAFT, SUBSTANTIATED, or CHALLENGED claims can be revoked",
        )
    claim["status"] = "REVOKED"
    touch(claim)
    return ok_obj(serializers.pub(claim))
