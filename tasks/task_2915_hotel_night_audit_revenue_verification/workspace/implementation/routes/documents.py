"""Approval paperwork: the evidence layer behind comp, rate and rebate gates."""
from flask import Blueprint

import db
import response
import shapes
from constants import DOC_TYPES, PREFIX, REVIEW_DECISIONS
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, FRONT_DESK_AGENT, NIGHT_AUDITOR,
                        REVENUE_MANAGER, authenticate)
from money import q2
from services import derive, lookup, serial

bp = Blueprint("documents", __name__, url_prefix=PREFIX)

FILING_ROLES = [FRONT_DESK_AGENT, NIGHT_AUDITOR, REVENUE_MANAGER, CONTROLLER]


def _mismatch(message):
    raise ApiError("ERR_DOCUMENT_TARGET_MISMATCH", message)


@bp.route("/authorization-documents", methods=["POST"])
def file_document():
    user_id, _role = authenticate(FILING_ROLES)
    body = shapes.parse([
        shapes.Field("property_id", "string", required=True),
        shapes.Field("doc_type", "string", required=True, enum=DOC_TYPES),
        shapes.Field("authorized_by_name", "string", required=True),
        shapes.Field("document_reference", "string", required=True),
        shapes.Field("valid_from_date", "date", required=True),
        shapes.Field("valid_to_date", "date", required=True),
        shapes.Field("folio_id", "string"),
        shapes.Field("allowance_id", "string"),
        shapes.Field("authorized_rate_amount", "number", ge=0),
    ])
    prop = lookup.get_property(body["property_id"])
    folio = lookup.get_folio(body["folio_id"]) if body["folio_id"] else None
    allowance = (lookup.get_allowance(body["allowance_id"])
                 if body["allowance_id"] else None)
    if folio is not None and folio["property_id"] != prop["id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The guest account belongs to a different property.")
    if allowance is not None:
        owner = db.store.folios.get(allowance["folio_id"])
        if owner is not None and owner["property_id"] != prop["id"]:
            raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                           "The allowance belongs to a different property.")
    doc_type = body["doc_type"]
    if doc_type in ("COMP_ROOM", "RATE_OVERRIDE"):
        if folio is None:
            _mismatch("%s paperwork requires folio_id." % doc_type)
        if allowance is not None:
            _mismatch("%s paperwork may not name an allowance." % doc_type)
        if doc_type == "RATE_OVERRIDE" and body["authorized_rate_amount"] is None:
            _mismatch("RATE_OVERRIDE paperwork requires authorized_rate_amount.")
    else:
        if allowance is None:
            _mismatch("ALLOWANCE_APPROVAL paperwork requires allowance_id.")
        if folio is not None:
            _mismatch("ALLOWANCE_APPROVAL paperwork may not name a folio.")
    if body["valid_from_date"] > body["valid_to_date"]:
        raise ApiError("ERR_SHIFT_WINDOW_INVALID",
                       "valid_from_date must be at or before valid_to_date.")
    if folio is not None:
        for other in lookup.documents_of_folio(folio["id"], doc_type):
            if other["status"] not in ("PENDING", "ACTIVE"):
                continue
            if body["valid_from_date"] <= other["valid_to_date"] and \
                    other["valid_from_date"] <= body["valid_to_date"]:
                raise ApiError("ERR_AUTHORIZATION_INTERVAL_OVERLAP",
                               "Another document already covers part of that interval.")
    rate = body["authorized_rate_amount"]
    row = db.insert("documents", {
        "_kind": "AuthorizationDocument",
        "property_id": prop["id"],
        "folio_id": folio["id"] if folio else None,
        "allowance_id": allowance["id"] if allowance else None,
        "doc_type": doc_type,
        "authorized_by_name": body["authorized_by_name"],
        "document_reference": body["document_reference"],
        "authorized_rate_amount": q2(rate) if rate is not None else None,
        "valid_from_date": body["valid_from_date"],
        "valid_to_date": body["valid_to_date"],
        "status": "PENDING",
        "reviewed_by_user_id": None,
        "filed_by_user_id": user_id,
        "reviewed_at": None,
    })
    return response.created(serial.document_out(row))


@bp.route("/authorization-documents/<row_id>/review", methods=["POST"])
def review_document(row_id):
    user_id, _role = authenticate([REVENUE_MANAGER, CONTROLLER])
    body = shapes.parse([
        shapes.Field("decision", "string", required=True, enum=REVIEW_DECISIONS),
    ])
    doc = lookup.get_document(row_id)
    if doc["status"] != "PENDING":
        raise ApiError("ERR_DOCUMENT_NOT_PENDING",
                       "The document has already been reviewed.")
    if doc["filed_by_user_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "The filer may not review their own paperwork.")
    doc["status"] = "ACTIVE" if body["decision"] == "APPROVE" else "REJECTED"
    doc["reviewed_by_user_id"] = user_id
    doc["reviewed_at"] = db.now()
    derive.touch(doc)
    return response.ok(serial.document_out(doc))


@bp.route("/authorization-documents/<row_id>/revoke", methods=["POST"])
def revoke_document(row_id):
    user_id, _role = authenticate([CONTROLLER])
    doc = lookup.get_document(row_id)
    if doc["status"] != "ACTIVE":
        raise ApiError("ERR_DOCUMENT_NOT_ACTIVE",
                       "Only active paperwork may be revoked.")
    doc["status"] = "REVOKED"
    doc["reviewed_by_user_id"] = user_id
    derive.touch(doc)
    return response.ok(serial.document_out(doc))


@bp.route("/authorization-documents/<row_id>", methods=["GET"])
def get_document(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.document_out(lookup.get_document(row_id)))


@bp.route("/authorization-documents", methods=["GET"])
def list_documents():
    authenticate(ALL_ROLES)
    rows = db.all_of("documents")
    for key in ("property_id", "folio_id", "allowance_id", "doc_type", "status"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.document_out)
    return response.collection(items, meta)
