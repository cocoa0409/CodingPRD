"""Append-only evidence records: the documentation trail and renewal analytics."""
from flask import Blueprint

import db
import response
import serialize
from errors import ApiError
from routes._common import CEDENT_READ, ordered_filtered, paged, q
from middleware import require

bp = Blueprint("evidence", __name__)


@bp.route("/contract-documents", methods=["GET"])
def list_contract_documents():
    require(CEDENT_READ)
    rows = ordered_filtered(db.contract_documents, [
        ("program_id", q("program_id")),
        ("document_type", q("document_type")),
    ])
    return paged(rows, serialize.contract_document)


@bp.route("/contract-documents/<document_id>", methods=["GET"])
def read_contract_document(document_id):
    require(CEDENT_READ)
    row = db.contract_documents.get(document_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_DOCUMENT_NOT_FOUND",
                       "contract document %s does not exist" % document_id, 404)
    return response.object_response(serialize.contract_document(row), 200)


@bp.route("/renewal-reports", methods=["GET"])
def list_renewal_reports():
    require(CEDENT_READ)
    rows = ordered_filtered(db.renewal_reports, [
        ("program_id", q("program_id")),
    ])
    return paged(rows, serialize.renewal_report)


@bp.route("/renewal-reports/<report_id>", methods=["GET"])
def read_renewal_report(report_id):
    require(CEDENT_READ)
    row = db.renewal_reports.get(report_id)
    if row is None:
        raise ApiError("ERR_RENEWAL_REPORT_NOT_FOUND",
                       "renewal report %s does not exist" % report_id, 404)
    return response.object_response(serialize.renewal_report(row), 200)
