"""Retailer paperwork: commitment coverage and performance evidence (PRD 3.5)."""

from flask import Blueprint, g

import calc
from db import db, new_row, touch
from errors import ApiError, bad_request
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    PREFIX,
    created_asc,
    created_desc,
    get_document,
    get_promotion,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_enum,
    get_instant,
    get_int,
    no_body,
    pagination,
    query_enum,
    query_value,
)

bp = Blueprint("documents", __name__)

KAM = "KeyAccountManager"
ANALYST = "TradeFinanceAnalyst"

DOC_CLASSES = ("COMMITMENT", "EVIDENCE")
DOC_TYPES = ("SIGNED_LOI", "PORTAL_ACK", "SCAN_DATA", "DISPLAY_PHOTO", "AD_TEARSHEET")
COMMITMENT_TYPES = ("SIGNED_LOI", "PORTAL_ACK")
EVIDENCE_TYPES = ("SCAN_DATA", "DISPLAY_PHOTO", "AD_TEARSHEET")
COVERS = ("TPR", "DISPLAY", "FEATURE", "ALL")
DOC_STATUSES = ("SUBMITTED", "VERIFIED")


@bp.post(PREFIX + "/promotions/<promotion_id>/documents")
def attach_document(promotion_id):
    authenticate([KAM, ANALYST])
    data = body_fields(
        required=["doc_class", "doc_type", "covers_tactic_type", "received_at"],
        optional=["units_verified"],
    )
    doc_class = get_enum(data, "doc_class", DOC_CLASSES)
    doc_type = get_enum(data, "doc_type", DOC_TYPES)
    covers = get_enum(data, "covers_tactic_type", COVERS)
    received_at = get_instant(data, "received_at")
    units = get_int(data, "units_verified", required=False, minimum=0)
    if units is None:
        units = 0
    legal = COMMITMENT_TYPES if doc_class == "COMMITMENT" else EVIDENCE_TYPES
    if doc_type not in legal:
        raise bad_request("doc_type %s is not a %s document kind." % (doc_type, doc_class))
    if doc_class == "COMMITMENT" and units > 0:
        raise bad_request("units_verified must be 0 on a COMMITMENT document.")

    promo = get_promotion(promotion_id)
    # rung 43 - every lifecycle except WITHDRAWN accepts paperwork
    if promo["lifecycle_status"] == "WITHDRAWN":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")

    row = new_row()
    row.update({
        "promotion_id": promotion_id,
        "doc_class": doc_class,
        "doc_type": doc_type,
        "covers_tactic_type": covers,
        "units_verified": units,
        "received_at": received_at,
        "status": "SUBMITTED",
        "verified_by_user_id": None,
    })
    db.documents[row["id"]] = row
    return created_response(calc.document_out(row))


@bp.get(PREFIX + "/promotions/<promotion_id>/documents")
def list_promotion_documents(promotion_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination(["doc_class", "status"])
    doc_class = query_enum("doc_class", DOC_CLASSES)
    status = query_enum("status", DOC_STATUSES)
    get_promotion(promotion_id)
    rows = calc.documents_of_promotion(promotion_id)
    if doc_class is not None:
        rows = [r for r in rows if r["doc_class"] == doc_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_asc(rows), limit, offset, calc.document_out)


@bp.get(PREFIX + "/documents")
def list_documents():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["promotion_id", "doc_class", "doc_type", "status"])
    promotion_id = query_value("promotion_id")
    doc_class = query_enum("doc_class", DOC_CLASSES)
    doc_type = query_enum("doc_type", DOC_TYPES)
    status = query_enum("status", DOC_STATUSES)
    rows = list(db.documents.values())
    if promotion_id is not None:
        get_promotion(promotion_id)
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if doc_class is not None:
        rows = [r for r in rows if r["doc_class"] == doc_class]
    if doc_type is not None:
        rows = [r for r in rows if r["doc_type"] == doc_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_desc(rows), limit, offset, calc.document_out)


@bp.get(PREFIX + "/documents/<document_id>")
def read_document(document_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.document_out(get_document(document_id)))


@bp.post(PREFIX + "/documents/<document_id>/verify")
def verify_document(document_id):
    authenticate([KAM, ANALYST])
    no_body()
    doc = get_document(document_id)
    # rung 45
    if doc["status"] != "SUBMITTED":
        raise ApiError("ERR_DOCUMENT_ALREADY_VERIFIED")
    # rung 52 - payload dependent authorisation
    required_role = KAM if doc["doc_class"] == "COMMITMENT" else ANALYST
    if g.user_role != required_role:
        raise ApiError("ERR_DOCUMENT_CLASS_ROLE_MISMATCH")
    doc["status"] = "VERIFIED"
    doc["verified_by_user_id"] = g.user_id
    touch(doc)
    promo = db.promotions.get(doc["promotion_id"])
    if promo is not None:
        touch(promo)
    return object_response(calc.document_out(doc))
