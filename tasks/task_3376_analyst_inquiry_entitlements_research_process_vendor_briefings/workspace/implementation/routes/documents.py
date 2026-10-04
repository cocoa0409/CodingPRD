"""ResearchDocument endpoints (PRD 3.5, 3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state, separation_violation
from middleware import (
    authenticate,
    body,
    enum,
    optional_int,
    optional_str,
    require_str,
)
from response import ok, ok_list
from services import documents as docsvc
from services import state
from timeutil import embargo_until
from routes._common import page_of, require_analyst, require_document

bp = Blueprint("documents", __name__)

DOC_TYPES = ("MARKET_GUIDE", "COMPARATIVE_MATRIX", "HYPE_PROFILE", "CRITICAL_CAPABILITIES")
PRACTICE_AREAS = ("CIO_TECH", "DATA_ANALYTICS", "SECURITY", "ERP_FINANCE")
VERDICTS = ("APPROVE", "REVISE")

DEFAULT_EMBARGO_DAYS = {
    "MARKET_GUIDE": 30,
    "COMPARATIVE_MATRIX": 45,
    "HYPE_PROFILE": 14,
    "CRITICAL_CAPABILITIES": 21,
}


@bp.post("/research/documents")
def create_document():
    authenticate(["Analyst", "ResearchDirector"])
    data = body()
    title = require_str(data, "title")
    doc_type = enum(require_str(data, "doc_type"), DOC_TYPES, "doc_type")
    practice_area = enum(require_str(data, "practice_area"), PRACTICE_AREAS, "practice_area")
    lead_analyst_id = require_str(data, "lead_analyst_id")
    embargo_days = optional_int(data, "embargo_days", None)
    if embargo_days is not None and embargo_days < 0:
        raise bad_request("embargo_days must be at least 0.")
    reviewer = optional_str(data, "peer_reviewer_analyst_id", "")

    require_analyst(lead_analyst_id)
    if reviewer:
        require_analyst(reviewer)

    document = db.create(
        title=title,
        doc_type=doc_type,
        practice_area=practice_area,
        lead_analyst_id=lead_analyst_id,
        editorial_status="DRAFT",
        embargo_status="EMBARGOED",
        embargo_days=embargo_days if embargo_days is not None else DEFAULT_EMBARGO_DAYS[doc_type],
        published_at=None,
        embargo_until=None,
        peer_reviewer_analyst_id=reviewer,
        peer_verdict="NOT_ASSIGNED",
        peer_review_round=0,
        fact_check_open_count=0,
        included_vendor_count=0,
        placement_locked=False,
        revision_count=0,
    )
    db.documents[document["id"]] = document
    return ok(serialize(document), 201)


@bp.get("/research/documents/<document_id>")
def read_document(document_id):
    role, _ = authenticate([
        "Analyst",
        "ResearchDirector",
        "ClientAdmin",
        "SeatHolder",
        "VendorRep",
        "ComplianceOfficer",
        "PlatformAdmin",
    ])
    document = require_document(document_id)
    state.evaluate_document_inclusions(document)
    state.evaluate_document(document)
    if role == "VendorRep" and document.get("embargo_status") == "EMBARGOED":
        raise ApiError(
            "ERR_EMBARGO_ACTIVE",
            "A vendor may not read a document whose embargo is still active.",
            403,
        )
    return ok(serialize(document), 200)


@bp.get("/research/documents")
def list_documents():
    authenticate(["Analyst", "ResearchDirector", "PlatformAdmin", "ComplianceOfficer"])
    items = list(db.documents.values())
    lead_analyst_id = request.args.get("lead_analyst_id")
    editorial_status = request.args.get("editorial_status")
    doc_type = request.args.get("doc_type")
    if lead_analyst_id:
        items = [d for d in items if d.get("lead_analyst_id") == lead_analyst_id]
    if editorial_status:
        items = [d for d in items if d.get("editorial_status") == editorial_status]
    if doc_type:
        items = [d for d in items if d.get("doc_type") == doc_type]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


@bp.post("/research/documents/<document_id>/submit-for-review")
def submit_for_review(document_id):
    authenticate(["Analyst", "ResearchDirector"])
    data = body()
    if "peer_reviewer_analyst_id" not in data:
        raise bad_request("Missing required field: peer_reviewer_analyst_id")
    reviewer = data.get("peer_reviewer_analyst_id")
    if reviewer is None or not isinstance(reviewer, str):
        raise bad_request("peer_reviewer_analyst_id must be a string.")
    document = require_document(document_id)
    if reviewer:
        require_analyst(reviewer)

    if document.get("editorial_status") not in ("DRAFT", "REVISED"):
        raise invalid_state("Only a DRAFT or REVISED document can be submitted for review.")

    if not reviewer or reviewer == document.get("lead_analyst_id"):
        raise separation_violation(
            "The peer reviewer must be set and must differ from the lead analyst."
        )

    document["peer_reviewer_analyst_id"] = reviewer
    document["editorial_status"] = "PEER_REVIEW"
    document["peer_verdict"] = "PENDING"
    document["peer_review_round"] = document.get("peer_review_round", 0) + 1
    db.touch(document)
    return ok(serialize(document), 200)


@bp.post("/research/documents/<document_id>/peer-verdicts")
def peer_verdict(document_id):
    role, user_id = authenticate(["Analyst"])
    data = body()
    verdict = enum(require_str(data, "verdict"), VERDICTS, "verdict")
    optional_str(data, "comments", "")
    document = require_document(document_id)

    if role == "Analyst" and user_id != document.get("peer_reviewer_analyst_id"):
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Only the assigned peer reviewer may return a verdict.",
            403,
        )
    if document.get("editorial_status") != "PEER_REVIEW":
        raise invalid_state("Only a document in PEER_REVIEW can receive a verdict.")

    if verdict == "REVISE":
        document["peer_verdict"] = "REVISE"
        document["editorial_status"] = "DRAFT"
        db.touch(document)
        return ok(serialize(document), 200)

    document["peer_verdict"] = "APPROVE"
    document["editorial_status"] = "FACT_CHECK"
    for inc in docsvc.inclusions_of(document["id"]):
        if inc.get("inclusion_status") == "INCLUDED":
            docsvc.open_fact_check_round(inc)
            db.touch(inc)
    docsvc.recompute_fact_check_open_count(document)
    db.touch(document)
    return ok(serialize(document), 200)


@bp.post("/research/documents/<document_id>/publish")
def publish_document(document_id):
    authenticate(["ResearchDirector"])
    document = require_document(document_id)
    if document.get("editorial_status") != "CLEARED":
        raise invalid_state("Only a CLEARED document can be published.")

    now = db.now()
    document["editorial_status"] = "PUBLISHED"
    document["placement_locked"] = True
    document["published_at"] = now
    document["embargo_status"] = "EMBARGOED"
    document["embargo_until"] = embargo_until(now, document.get("embargo_days", 0))

    # Three-step freeze cascade (PRD 3.6).
    for inc in docsvc.inclusions_of(document["id"]):
        inc["placement_locked"] = True
        status = inc.get("inclusion_status")
        if status == "INCLUDED":
            vendor_obj = db.vendors.get(inc.get("vendor_id"))
            if vendor_obj is not None:
                state.recompute_vendor_eligibility(vendor_obj)
                db.touch(vendor_obj)
        elif status == "EXCLUDED":
            inc["appeal_window_closes_at"] = now + timedelta(days=30)
        db.touch(inc)
    docsvc.recompute_included_vendor_count(document)
    db.touch(document)
    return ok(serialize(document), 200)


@bp.post("/research/documents/<document_id>/revise")
def revise_document(document_id):
    authenticate(["Analyst", "ResearchDirector"])
    data = body()
    require_str(data, "revision_reason")
    document = require_document(document_id)
    if document.get("editorial_status") != "PUBLISHED":
        raise invalid_state("Only a PUBLISHED document can be revised.")

    document["editorial_status"] = "REVISED"
    document["placement_locked"] = False
    document["revision_count"] = document.get("revision_count", 0) + 1
    db.touch(document)

    for inc in docsvc.inclusions_of(document["id"]):
        if inc.get("inclusion_status") in ("INCLUDED", "APPEAL_UPHELD"):
            inc["placement_locked"] = False
            docsvc.open_fact_check_round(inc)
            db.touch(inc)

    docsvc.recompute_fact_check_open_count(document)
    if any(
        inc.get("fact_check_status") == "REQUESTED"
        for inc in docsvc.inclusions_of(document["id"])
    ):
        document["editorial_status"] = "FACT_CHECK"
    db.touch(document)
    return ok(serialize(document), 200)
