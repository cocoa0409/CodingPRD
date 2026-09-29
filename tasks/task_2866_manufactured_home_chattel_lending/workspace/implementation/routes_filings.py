"""Lien perfection: tender, agency response and the rejection cycle (PRD 3.5)."""

from flask import Blueprint, request

import constants as K
import core
import envelope
import security
import shape
import store
from errors import ApiError
from routes_units import query_enum

bp = Blueprint("filings", __name__)


def compute_missing(filing_type, submitted):
    return [code for code in K.REQUIRED_DOCUMENTS[filing_type] if code not in submitted]


@bp.post("/lien-filings")
def create_filing():
    security.require(security.CLOSING_AGENT)
    data = shape.body()

    loan = store.get_loan(shape.req_id(data, "loan_id"))
    filing_type = shape.req_enum(data, "filing_type", K.FILING_TYPES)
    submitted = shape.req_list(data, "submitted_documents")

    if filing_type != K.FILING_TYPE_FOR_CLASSIFICATION[loan["collateral_classification"]]:
        raise ApiError("ERR_FILING_TYPE_MISMATCH")

    missing = compute_missing(filing_type, submitted)
    if missing:
        raise ApiError("ERR_FILING_DOCUMENTS_INCOMPLETE")

    record = {
        "id": core.new_id(),
        "loan_id": loan["id"],
        "unit_id": loan["unit_id"],
        "filing_type": filing_type,
        "submitted_documents": list(submitted),
        "missing_documents": missing,
        "status": "SUBMITTED",
        "attempt_number": 1,
        "agency_reference": None,
        "rejection_code": None,
        "recorded_at": None,
        "released_at": None,
        "_release_cause": None,
    }
    store.stamp_new(record)
    store.filings[record["id"]] = record

    loan["perfection_state"] = "FILING_SUBMITTED"
    store.touch(loan)
    return envelope.created(store.serialize(record))


@bp.get("/lien-filings/<filing_id>")
def read_filing(filing_id):
    security.require(*security.STAFF)
    return envelope.ok(store.serialize(store.get_filing(filing_id)))


@bp.get("/lien-filings")
def list_filings():
    security.require(*security.STAFF)
    loan_id = request.args.get("loan_id")
    unit_id = request.args.get("unit_id")
    filing_type = query_enum("filing_type", K.FILING_TYPES)
    status = query_enum("status", K.FILING_STATUSES)

    rows = store.ordered(list(store.filings.values()))
    if loan_id:
        rows = [f for f in rows if f["loan_id"] == loan_id]
    if unit_id:
        rows = [f for f in rows if f["unit_id"] == unit_id]
    if filing_type:
        rows = [f for f in rows if f["filing_type"] == filing_type]
    if status:
        rows = [f for f in rows if f["status"] == status]
    return envelope.paginate(rows, store.serialize)


@bp.post("/lien-filings/<filing_id>/agency-response")
def agency_response(filing_id):
    security.require(security.PLATFORM_ADMIN)
    filing = store.get_filing(filing_id)
    data = shape.body()
    outcome = shape.req_enum(data, "outcome", K.AGENCY_OUTCOMES)
    agency_reference = shape.opt_string(data, "agency_reference")
    rejection_code = shape.opt_enum(data, "rejection_code", K.REJECTION_CODES)

    if filing["status"] != "SUBMITTED":
        raise ApiError("ERR_FILING_INVALID_STATE")

    loan = store.loans.get(filing["loan_id"])
    if outcome == "RECORDED":
        if filing["missing_documents"]:
            raise ApiError("ERR_FILING_DOCUMENTS_INCOMPLETE")
        filing["status"] = "RECORDED"
        filing["agency_reference"] = agency_reference
        filing["recorded_at"] = core.now()
        if loan is not None:
            loan["perfection_state"] = "PERFECTED"
        if filing["filing_type"] == "TITLE_LIEN":
            unit = store.units.get(filing["unit_id"])
            if unit is not None and unit["title_status"] == "ACTIVE_TITLE":
                unit["title_status"] = "TITLE_ENCUMBERED"
                store.touch(unit)
    else:
        filing["status"] = "REJECTED"
        filing["rejection_code"] = rejection_code
        if loan is not None:
            loan["perfection_state"] = "UNPERFECTED"

    store.touch(filing)
    if loan is not None:
        store.touch(loan)
    return envelope.ok(store.serialize(filing))


@bp.post("/lien-filings/<filing_id>/resubmit")
def resubmit_filing(filing_id):
    security.require(security.CLOSING_AGENT)
    filing = store.get_filing(filing_id)
    data = shape.body()
    submitted = shape.req_list(data, "submitted_documents")

    if filing["status"] != "REJECTED":
        raise ApiError("ERR_FILING_INVALID_STATE")

    missing = compute_missing(filing["filing_type"], submitted)
    if missing:
        raise ApiError("ERR_FILING_DOCUMENTS_INCOMPLETE")
    if filing["attempt_number"] >= K.MAX_FILING_ATTEMPTS:
        raise ApiError("ERR_FILING_ATTEMPT_LIMIT")

    filing["submitted_documents"] = list(submitted)
    filing["missing_documents"] = missing
    filing["status"] = "SUBMITTED"
    filing["attempt_number"] = filing["attempt_number"] + 1
    filing["rejection_code"] = None
    store.touch(filing)

    loan = store.loans.get(filing["loan_id"])
    if loan is not None:
        loan["perfection_state"] = "FILING_SUBMITTED"
        store.touch(loan)
    return envelope.ok(store.serialize(filing))
