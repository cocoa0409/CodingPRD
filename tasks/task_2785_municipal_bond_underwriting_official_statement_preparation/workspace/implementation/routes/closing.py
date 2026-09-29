"""Closing documents: execution and waiver (PRD 3.9)."""
from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import authenticate
from services import derive
from validation import parse_body, query_value, sorted_rows, spec

bp = Blueprint("closing", __name__)

READ_ROLES = [
    "IssuerOfficial",
    "MunicipalAdvisor",
    "Underwriter",
    "BondCounsel",
    "ComplianceOfficer",
]
NEVER_WAIVABLE = ("BOND_OPINION", "TAX_CERTIFICATE")


@bp.route("/bond-offerings/deals/<deal_id>/closing-documents", methods=["GET"])
def list_deal_documents(deal_id):
    authenticate(READ_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted_rows(lookup.documents_of_deal(deal_id))
    doc_type = query_value("doc_type")
    if doc_type is not None:
        rows = [row for row in rows if row["doc_type"] == doc_type]
    execution_status = query_value("execution_status")
    if execution_status is not None:
        rows = [row for row in rows if row["execution_status"] == execution_status]
    return response.paginated(rows, serializers.document)


@bp.route("/bond-offerings/closing-documents/<document_id>", methods=["GET"])
def read_document(document_id):
    authenticate(READ_ROLES)
    row = lookup.get_document(document_id)
    return response.ok(serializers.document(row))


@bp.route("/bond-offerings/closing-documents/<document_id>/execute", methods=["POST"])
def execute_document(document_id):
    actor = authenticate(["BondCounsel", "IssuerOfficial", "Underwriter", "MunicipalAdvisor"])
    document = lookup.get_document(document_id)
    body = parse_body([spec("signatory_name", "string", min_len=1, max_len=120)])
    deal = db.db.deals[document["deal_id"]]
    # tier 11: the document must still be awaiting signature
    if document["execution_status"] != "PENDING":
        raise ApiError("ERR_CLOSING_DOC_ALREADY_EXECUTED")
    # tier 12: only the named signatory role may sign
    if actor.role != document["signatory_role"]:
        raise ApiError("ERR_SIGNATORY_ROLE_INVALID")
    if deal["status"] != "AWARDED":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # tiers 13 and 16: the cross-entity gates, by document type
    doc_type = document["doc_type"]
    if doc_type == "BOND_OPINION":
        statement = derive.governing_statement(deal["id"])
        if statement is None or statement["status"] != "FINAL_POSTED":
            raise ApiError("ERR_OS_NOT_FINAL_POSTED")
    elif doc_type == "CONTINUING_DISCLOSURE_AGREEMENT":
        if derive.active_undertaking(deal["id"]) is None:
            raise ApiError("ERR_UNDERTAKING_NOT_ACTIVE")
    elif doc_type == "TAX_CERTIFICATE":
        if (
            deal["arbitrage_yield_pct"] is None
            or deal["post_issuance_handoff_status"] != "READY"
        ):
            raise ApiError("ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE")
    document["execution_status"] = "EXECUTED"
    document["signatory_name"] = body["signatory_name"]
    document["executed_at"] = db.now()
    db.touch(document)
    return response.ok(serializers.document(document))


@bp.route("/bond-offerings/closing-documents/<document_id>/waive", methods=["POST"])
def waive_document(document_id):
    authenticate(["ComplianceOfficer"])
    document = lookup.get_document(document_id)
    body = parse_body([spec("waiver_reason", "string", min_len=1)])
    deal = db.db.deals[document["deal_id"]]
    if document["execution_status"] != "PENDING":
        raise ApiError("ERR_CLOSING_DOC_ALREADY_EXECUTED")
    if deal["status"] != "AWARDED":
        raise ApiError("ERR_DEAL_INVALID_STATE")
    # tier 12: the never-waivable pair
    if document["doc_type"] in NEVER_WAIVABLE:
        raise ApiError("ERR_SIGNATORY_ROLE_INVALID")
    document["execution_status"] = "WAIVED"
    document["waiver_reason"] = body["waiver_reason"]
    db.touch(document)
    return response.ok(serializers.document(document))
