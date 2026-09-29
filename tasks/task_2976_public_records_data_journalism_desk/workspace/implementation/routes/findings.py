"""Finding endpoints (PRD section 3.8)."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_DATA_REPORTER, ROLE_MANAGING_EDITOR,
                        authenticate)
from services import cascades
from services import investigation as inv_service

bp = Blueprint("findings", __name__)

REVOCABLE_STATUSES = ("DOC_MATCHED", "SME_CONFIRMED", "SME_DISPUTED")


def _invalid_finding_state(finding):
    return ApiError(
        "ERR_INVALID_FINDING_STATE",
        "The operation is not declared from verification_status %s." % finding["verification_status"],
    )


@bp.post("/findings")
def create_finding():
    authenticate([ROLE_DATA_REPORTER])
    payload = v.body()
    investigation_id = v.field_string(payload, "investigation_id", min_len=1, non_blank=True)
    analysis_run_id = v.field_string(payload, "analysis_run_id", min_len=1, non_blank=True)
    claim_text = v.field_string(payload, "claim_text", min_len=1, max_len=1000, non_blank=True)
    # Rung 6 -- references in declared order
    investigation = db.get_investigation(investigation_id)
    run = db.get_run(analysis_run_id)
    # Rung 31 -- the run must belong to the same investigation
    if run["investigation_id"] != investigation_id:
        raise ApiError("ERR_DATASET_NOT_LINKED",
                       "The named analysis run belongs to a different investigation.")
    finding = db.insert("findings", {
        "investigation_id": investigation_id,
        "analysis_run_id": analysis_run_id,
        "claim_text": claim_text,
        "source_document_ref": None,
        "matched_page": None,
        "verification_status": "UNVERIFIED",
        "sme_verdict_rationale": None,
    })
    investigation["finding_count"] = investigation["finding_count"] + 1
    inv_service.move_bucket(investigation, None, "UNVERIFIED")
    inv_service.recompute_readiness(investigation)
    db.touch(investigation)
    return response.created_response(db.serialize(finding))


@bp.get("/findings/<finding_id>")
def get_finding(finding_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_finding(finding_id)))


@bp.get("/findings")
def list_findings():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("findings"),
                           ["investigation_id", "analysis_run_id", "verification_status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/findings/<finding_id>/document-match")
def document_match(finding_id):
    authenticate([ROLE_DATA_REPORTER])
    finding = db.get_finding(finding_id)
    payload = v.body()
    source_document_ref = v.field_string(payload, "source_document_ref", min_len=1,
                                         max_len=200, non_blank=True)
    matched_page = v.field_int(payload, "matched_page")
    if finding["verification_status"] != "UNVERIFIED":
        raise _invalid_finding_state(finding)
    finding["verification_status"] = "DOC_MATCHED"
    finding["source_document_ref"] = source_document_ref
    finding["matched_page"] = matched_page
    db.touch(finding)
    investigation = db.find("investigations", finding["investigation_id"])
    if investigation is not None:
        inv_service.move_bucket(investigation, "UNVERIFIED", "DOC_MATCHED")
        inv_service.recompute_readiness(investigation)
        db.touch(investigation)
    return response.object_response(db.serialize(finding))


@bp.post("/findings/<finding_id>/verification-revocation")
def verification_revocation(finding_id):
    authenticate([ROLE_MANAGING_EDITOR])
    finding = db.get_finding(finding_id)
    payload = v.body()
    v.field_text(payload, "reason")
    if finding["verification_status"] not in REVOCABLE_STATUSES:
        raise _invalid_finding_state(finding)
    investigation = db.find("investigations", finding["investigation_id"])
    cascades.revoke_verification(finding, investigation)
    return response.object_response(db.serialize(finding))
