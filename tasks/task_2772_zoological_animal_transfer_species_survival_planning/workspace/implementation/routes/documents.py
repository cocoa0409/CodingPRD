from datetime import timedelta

from flask import Blueprint, g

import calc
import db
import services
from core import (actor, auth, body, fail, fmt_date, get_date, get_enum, get_str, now_date, ok,
                  pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("documents", __name__)

TYPES = ("INTERSTATE_CVI", "STATE_IMPORT_PERMIT", "CITES_EXPORT_PERMIT", "CITES_IMPORT_PERMIT",
         "USDA_TRANSPORT_PERMIT")
STATUSES = ("DRAFT", "ISSUED", "DENIED", "VOIDED")


@bp.post("/compliance-documents")
@auth("Registrar")
def create_document():
    b = body()
    agreement_id = get_str(b, "transfer_agreement_id", required=True)
    document_type = get_enum(b, "document_type", TYPES, required=True)
    vet_id = get_str(b, "issuing_veterinarian_id")
    authority = get_str(b, "issuing_authority_name")
    exam_date, exam_raw = get_date(b, "exam_date")

    if document_type == "INTERSTATE_CVI":
        if vet_id is None:
            fail("ERR_INVALID_REQUEST", "issuing_veterinarian_id is required for an INTERSTATE_CVI.")
        if exam_raw is None:
            fail("ERR_INVALID_REQUEST", "exam_date is required for an INTERSTATE_CVI.")
        if authority is not None:
            fail("ERR_INVALID_REQUEST", "issuing_authority_name must be null for an INTERSTATE_CVI.")
    else:
        if authority is None:
            fail("ERR_INVALID_REQUEST", "issuing_authority_name is required for a permit.")
        if vet_id is not None:
            fail("ERR_INVALID_REQUEST", "issuing_veterinarian_id must be null for a permit.")
        if exam_raw is not None:
            fail("ERR_INVALID_REQUEST", "exam_date must be null for a permit.")

    agreement = db.get_agreement(agreement_id)
    if vet_id is not None:
        db.get_vet(vet_id)

    services.party_check(agreement, actor(), "sending_institution_id")

    if agreement["status"] not in ("ACCEPTED", "EXECUTED"):
        fail("ERR_AGREEMENT_INVALID_STATE")

    doc = db.insert(db.documents, {
        "transfer_agreement_id": agreement_id,
        "document_type": document_type,
        "issuing_veterinarian_id": vet_id,
        "issuing_authority_name": authority,
        "exam_date": exam_raw,
        "document_number": None,
        "valid_from": None,
        "valid_until": None,
        "status": "DRAFT",
        "decision_note": None,
    })
    return ok(services.document_out(doc), 201)


@bp.post("/compliance-documents/<document_id>/decision")
@auth("Veterinarian", "AccreditationAdmin")
def decide_document(document_id):
    b = body()
    outcome = get_enum(b, "outcome", ("ISSUE", "DENY"), required=True)
    document_number = get_str(b, "document_number")
    valid_until, valid_until_raw = get_date(b, "valid_until")
    decision_note = get_str(b, "decision_note")

    doc = db.get_document(document_id)
    agreement = db.agreements.get(doc["transfer_agreement_id"])
    sending = db.institutions.get(agreement["sending_institution_id"]) if agreement else None
    is_cvi = doc["document_type"] == "INTERSTATE_CVI"

    # rung 5 -- issuing authority is split strictly by kind, for both outcomes alike
    if is_cvi:
        if g.role != "Veterinarian" or actor() != doc["issuing_veterinarian_id"]:
            fail("ERR_WRONG_ISSUING_AUTHORITY")
    elif g.role != "AccreditationAdmin":
        fail("ERR_WRONG_ISSUING_AUTHORITY")

    vet = db.veterinarians.get(doc["issuing_veterinarian_id"]) if is_cvi else None
    if is_cvi and sending is not None and vet is not None \
            and vet["institution_id"] != sending["id"]:
        fail("ERR_VET_INSTITUTION_MISMATCH")

    if is_cvi and outcome == "ISSUE":
        # rung 6 -- the vet who drew the blood may not sign the certificate
        for t in services.tests_of(agreement["id"]):
            if t["collecting_veterinarian_id"] == vet["id"]:
                fail("ERR_SEGREGATION_OF_DUTIES")

    # rung 8 -- a document is decided once
    if doc["status"] != "DRAFT":
        fail("ERR_DOCUMENT_ALREADY_DECIDED")

    if is_cvi and outcome == "ISSUE":
        # rung 9 -- licence, jurisdiction and federal accreditation category
        if vet["license_status"] != "ACTIVE":
            fail("ERR_VET_LICENSE_INVALID")
        if sending is not None and vet["license_jurisdiction"] != sending["jurisdiction_code"]:
            fail("ERR_VET_LICENSE_INVALID")
        if agreement["transfer_scope"] == "INTERNATIONAL" \
                and vet["usda_accreditation_category"] != "CATEGORY_II":
            fail("ERR_VET_NOT_ACCREDITED_FOR_SCOPE")

        panel = calc.REQUIRED_TEST_PANEL[agreement["transfer_scope"]]
        tests = services.tests_of(agreement["id"])
        # rung 10 -- results first, then completeness
        for t in tests:
            if t["test_code"] in panel and t["result"] in ("POSITIVE", "INCONCLUSIVE"):
                fail("ERR_POSITIVE_TEST_RESULT")
        exam = services.as_date(doc["exam_date"])
        for code in panel:
            fresh = False
            for t in tests:
                if t["test_code"] != code:
                    continue
                gap = calc.whole_days(services.as_date(t["collected_on"]), exam)
                if 0 <= gap <= calc.TEST_VALIDITY_DAYS:
                    fresh = True
            if not fresh:
                fail("ERR_TEST_PANEL_INCOMPLETE")

    if outcome == "ISSUE":
        doc["status"] = "ISSUED"
        doc["document_number"] = document_number
        if is_cvi:
            exam = services.as_date(doc["exam_date"])
            doc["valid_from"] = doc["exam_date"]
            doc["valid_until"] = fmt_date(exam + timedelta(days=calc.CVI_VALIDITY_DAYS))
        else:
            doc["valid_from"] = fmt_date(now_date())
            doc["valid_until"] = valid_until_raw
    else:
        doc["status"] = "DENIED"
    doc["decision_note"] = decision_note
    db.touch(doc)
    return ok(services.document_out(doc))


@bp.get("/compliance-documents/<document_id>")
@auth()
def read_document(document_id):
    return ok(services.document_out(db.get_document(document_id)))


@bp.get("/compliance-documents")
@auth()
def list_documents():
    limit, offset = pagination()
    filters = {
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "issuing_veterinarian_id": q_str("issuing_veterinarian_id"),
        "document_type": q_enum("document_type", TYPES),
        "status": q_enum("status", STATUSES),
    }
    rows = list(db.documents.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.document_out)
