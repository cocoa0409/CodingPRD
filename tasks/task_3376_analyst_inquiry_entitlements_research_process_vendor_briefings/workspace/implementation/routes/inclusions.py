"""VendorInclusion endpoints (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state, unauthorized
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
from services.scoring import q2
from timeutil import parse_dt
from routes._common import (
    page_of,
    require_document,
    require_inclusion,
    require_vendor,
)

bp = Blueprint("inclusions", __name__)

REPRINT_TIERS = ("NONE", "STANDARD", "PREMIUM")
MARKETING_USES = ("NO_USE", "INTERNAL_ONLY", "SOCIAL_SNIPPET", "FULL_REPRINT")
FINALIZE_OUTCOMES = ("INCLUDE", "EXCLUDE")
APPEAL_OUTCOMES = ("UPHOLD", "DENY")
FACT_CHECK_OUTCOMES = ("ACCEPT", "DISPUTE")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _dimension_scores(data):
    rows = data.get("dimension_scores")
    if not isinstance(rows, list) or not rows:
        raise bad_request("dimension_scores must be a non-empty array.")
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            raise bad_request("Each dimension_scores row must be an object.")
        dimension = row.get("dimension")
        raw_score = _number(row.get("raw_score"))
        weight_pct = _number(row.get("weight_pct"))
        if not isinstance(dimension, str) or not dimension:
            raise bad_request("Each dimension_scores row needs a dimension name.")
        if raw_score is None or weight_pct is None:
            raise bad_request("dimension_scores rows need numeric raw_score and weight_pct.")
        if raw_score < 0 or raw_score > 5:
            raise bad_request("raw_score must be between 0.00 and 5.00.")
        if weight_pct < 0 or weight_pct > 1:
            raise bad_request("weight_pct must be between 0 and 1.")
        cleaned.append(
            {"dimension": dimension, "raw_score": raw_score, "weight_pct": weight_pct}
        )
    if not docsvc.weights_sum_ok(cleaned):
        raise bad_request("dimension_scores weights must sum to exactly 1.00.")
    return cleaned


def _vendor_owns(role, user_id, inclusion_obj):
    if role == "VendorRep" and user_id != inclusion_obj.get("vendor_id"):
        raise unauthorized("A VendorRep may only act for its own vendor.")


@bp.post("/research/documents/<document_id>/vendor-inclusions")
def create_inclusion(document_id):
    authenticate(["Analyst", "ResearchDirector"])
    data = body()
    vendor_id = require_str(data, "vendor_id")
    rows = _dimension_scores(data)
    criteria = data.get("inclusion_criteria_met_count")
    if isinstance(criteria, bool) or not isinstance(criteria, int):
        raise bad_request("inclusion_criteria_met_count must be an integer.")
    if criteria < 0 or criteria > 6:
        raise bad_request("inclusion_criteria_met_count must be between 0 and 6.")
    expected_version = data.get("expected_document_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise bad_request("expected_document_version must be an integer.")
    reprint_tier = enum(optional_str(data, "reprint_tier", "NONE") or "NONE", REPRINT_TIERS, "reprint_tier")
    marketing_use = enum(
        optional_str(data, "permitted_marketing_use", "NO_USE") or "NO_USE",
        MARKETING_USES,
        "permitted_marketing_use",
    )
    authorized = optional_int(data, "reprint_copies_authorized", 0)
    if authorized is None:
        authorized = 0
    if authorized < 0:
        raise bad_request("reprint_copies_authorized must be at least 0.")

    document = require_document(document_id)
    require_vendor(vendor_id)

    if expected_version != document.get("version"):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_document_version does not match the document's current version.",
            412,
        )

    inclusion_obj = db.create(
        document_id=document["id"],
        vendor_id=vendor_id,
        inclusion_status="UNDER_EVALUATION",
        fact_check_status="NOT_STARTED",
        dimension_scores=rows,
        weighted_total_score=float(docsvc.weighted_total_score(rows)),
        inclusion_criteria_met_count=criteria,
        criteria_evaluated_at=db.now(),
        fact_check_round=0,
        fact_check_due_utc=None,
        fact_check_requested_at=None,
        fact_check_response_at=None,
        fact_check_late=False,
        reprint_tier=reprint_tier,
        permitted_marketing_use=marketing_use,
        reprint_copies_authorized=authorized,
        reprint_copies_used=0,
        reprint_fee_cents=0,
        appeal_filed_at=None,
        appeal_grounds="",
        appeal_count=0,
        appeal_window_closes_at=None,
        placement_locked=False,
        lead_analyst_conflicted=docsvc.lead_analyst_conflicted(document, vendor_id),
        _late_streak=0,
    )
    docsvc.refresh_reprint_fee(inclusion_obj)
    db.inclusions[inclusion_obj["id"]] = inclusion_obj

    # A newer row for the same (document, vendor) pair supersedes the older one.
    for other in docsvc.inclusions_of(document["id"]):
        if other["id"] == inclusion_obj["id"]:
            continue
        if other.get("vendor_id") != vendor_id:
            continue
        if other.get("inclusion_status") == "INCLUDED":
            other["inclusion_status"] = "SUPERSEDED"
            other["placement_locked"] = False
            db.touch(other)

    docsvc.recompute_included_vendor_count(document)
    db.touch(document)
    return ok(serialize(inclusion_obj), 201)


@bp.get("/research/vendor-inclusions/<inclusion_id>")
def read_inclusion(inclusion_id):
    authenticate(["Analyst", "ResearchDirector", "VendorRep", "ComplianceOfficer", "PlatformAdmin"])
    inclusion_obj = require_inclusion(inclusion_id)
    docsvc.evaluate_inclusion_lapse(inclusion_obj)
    return ok(serialize(inclusion_obj), 200)


@bp.get("/research/vendor-inclusions")
def list_inclusions():
    authenticate(["Analyst", "ResearchDirector", "VendorRep", "ComplianceOfficer", "PlatformAdmin"])
    items = list(db.inclusions.values())
    document_id = request.args.get("document_id")
    vendor_id = request.args.get("vendor_id")
    inclusion_status = request.args.get("inclusion_status")
    if document_id:
        items = [i for i in items if i.get("document_id") == document_id]
    if vendor_id:
        items = [i for i in items if i.get("vendor_id") == vendor_id]
    if inclusion_status:
        items = [i for i in items if i.get("inclusion_status") == inclusion_status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


@bp.post("/research/vendor-inclusions/<inclusion_id>/finalize")
def finalize_inclusion(inclusion_id):
    authenticate(["ResearchDirector"])
    data = body()
    outcome = enum(require_str(data, "outcome"), FINALIZE_OUTCOMES, "outcome")
    inclusion_obj = require_inclusion(inclusion_id)

    if inclusion_obj.get("inclusion_status") != "UNDER_EVALUATION":
        raise invalid_state("Only an UNDER_EVALUATION inclusion can be finalized.")

    if inclusion_obj.get("lead_analyst_conflicted"):
        raise ApiError(
            "ERR_SEPARATION_OF_DUTIES_VIOLATION",
            "The document's lead analyst holds an active sales relationship with this vendor.",
            403,
        )

    document = db.documents.get(inclusion_obj.get("document_id"))
    if outcome == "INCLUDE":
        if inclusion_obj.get("inclusion_criteria_met_count", 0) < 4:
            raise ApiError(
                "ERR_INCLUSION_CRITERIA_NOT_MET",
                "At least 4 of the six inclusion criteria must be met.",
                409,
            )
        if float(inclusion_obj.get("weighted_total_score", 0)) < 2.50:
            raise ApiError(
                "ERR_INCLUSION_CRITERIA_NOT_MET",
                "The weighted total score is below 2.50.",
                409,
            )
        inclusion_obj["inclusion_status"] = "INCLUDED"
        docsvc.refresh_reprint_fee(inclusion_obj)
        db.touch(inclusion_obj)
        if document is not None:
            docsvc.recompute_included_vendor_count(document)
            db.touch(document)
        return ok(serialize(inclusion_obj), 200)

    inclusion_obj["inclusion_status"] = "EXCLUDED"
    docsvc.refresh_reprint_fee(inclusion_obj)
    if document is not None and docsvc.document_is_published(document):
        published = parse_dt(document.get("published_at"))
        if published is not None:
            inclusion_obj["appeal_window_closes_at"] = published + timedelta(days=30)
    db.touch(inclusion_obj)
    return ok(serialize(inclusion_obj), 200)


@bp.post("/research/vendor-inclusions/<inclusion_id>/appeals")
def file_appeal(inclusion_id):
    role, user_id = authenticate(["VendorRep"])
    data = body()
    grounds = require_str(data, "appeal_grounds")
    inclusion_obj = require_inclusion(inclusion_id)
    _vendor_owns(role, user_id, inclusion_obj)

    if inclusion_obj.get("inclusion_status") not in ("EXCLUDED", "APPEAL_DENIED"):
        raise invalid_state("Only an EXCLUDED or APPEAL_DENIED placement can be appealed.")

    document = db.documents.get(inclusion_obj.get("document_id"))
    if document is None or not docsvc.document_is_published(document):
        raise invalid_state("The parent document must be PUBLISHED before an appeal.")

    closes_at = parse_dt(inclusion_obj.get("appeal_window_closes_at"))
    if closes_at is None or db.now() > closes_at:
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED",
            "The appeal was filed after appeal_window_closes_at.",
            409,
        )

    if inclusion_obj.get("appeal_count", 0) >= 2:
        raise ApiError(
            "ERR_APPEAL_LIMIT_REACHED",
            "This inclusion has already been appealed twice.",
            409,
        )

    inclusion_obj["inclusion_status"] = "UNDER_APPEAL"
    inclusion_obj["appeal_filed_at"] = db.now()
    inclusion_obj["appeal_grounds"] = grounds
    inclusion_obj["appeal_count"] = inclusion_obj.get("appeal_count", 0) + 1
    db.touch(inclusion_obj)
    return ok(serialize(inclusion_obj), 200)


@bp.post("/research/vendor-inclusions/<inclusion_id>/appeal-decisions")
def decide_appeal(inclusion_id):
    authenticate(["ResearchDirector"])
    data = body()
    outcome = enum(require_str(data, "outcome"), APPEAL_OUTCOMES, "outcome")
    optional_str(data, "rationale", "")
    inclusion_obj = require_inclusion(inclusion_id)

    if inclusion_obj.get("inclusion_status") != "UNDER_APPEAL":
        raise invalid_state("Only an UNDER_APPEAL inclusion can be decided.")

    document = db.documents.get(inclusion_obj.get("document_id"))

    if outcome == "DENY":
        inclusion_obj["inclusion_status"] = "APPEAL_DENIED"
        db.touch(inclusion_obj)
        return ok(serialize(inclusion_obj), 200)

    inclusion_obj["inclusion_status"] = "APPEAL_UPHELD"
    db.touch(inclusion_obj)
    if document is None:
        return ok(serialize(inclusion_obj), 200)

    docsvc.recompute_included_vendor_count(document)
    if docsvc.document_is_published(document):
        document["editorial_status"] = "REVISED"
        document["placement_locked"] = False
        document["revision_count"] = document.get("revision_count", 0) + 1
        for inc in docsvc.inclusions_of(document["id"]):
            if inc.get("inclusion_status") in ("INCLUDED", "APPEAL_UPHELD"):
                docsvc.open_fact_check_round(inc)
                db.touch(inc)
        docsvc.recompute_fact_check_open_count(document)
        db.touch(document)
    else:
        db.touch(document)
    return ok(serialize(inclusion_obj), 200)


@bp.post("/research/vendor-inclusions/<inclusion_id>/fact-check-responses")
def fact_check_response(inclusion_id):
    role, user_id = authenticate(["VendorRep"])
    data = body()
    require_str(data, "response_summary")
    correction = data.get("correction_offered")
    if not isinstance(correction, bool):
        raise bad_request("correction_offered must be a boolean.")
    inclusion_obj = require_inclusion(inclusion_id)
    _vendor_owns(role, user_id, inclusion_obj)

    status = inclusion_obj.get("fact_check_status")
    if status == "LAPSED":
        raise ApiError(
            "ERR_FACT_CHECK_RESPONSE_LATE",
            "The fact-check cycle already lapsed because the clock passed the deadline.",
            409,
        )
    if status != "REQUESTED":
        raise invalid_state("Only an inclusion in REQUESTED can receive a fact-check response.")

    if inclusion_obj.get("lead_analyst_conflicted"):
        raise ApiError(
            "ERR_SEPARATION_OF_DUTIES_VIOLATION",
            "The document's lead analyst holds an active sales relationship with this vendor.",
            403,
        )

    due = docsvc.due_of(inclusion_obj)
    if due is not None and db.now() > due:
        inclusion_obj["fact_check_status"] = "LAPSED"
        inclusion_obj["fact_check_late"] = True
        db.touch(inclusion_obj)
        document = db.documents.get(inclusion_obj.get("document_id"))
        if document is not None:
            docsvc.recompute_fact_check_open_count(document)
            db.touch(document)
        raise ApiError(
            "ERR_FACT_CHECK_RESPONSE_LATE",
            "The fact-check cycle already lapsed because the clock passed the deadline.",
            409,
        )

    late = due is not None and db.now() > due
    inclusion_obj["fact_check_status"] = "VENDOR_RESPONDED"
    inclusion_obj["fact_check_response_at"] = db.now()
    inclusion_obj["fact_check_late"] = late
    if late:
        penalty = q2(float(inclusion_obj.get("weighted_total_score", 0)) - 0.25)
        if penalty < 0:
            penalty = q2(0)
        inclusion_obj["weighted_total_score"] = float(penalty)
        streak = inclusion_obj.get("_late_streak", 0) + 1
        inclusion_obj["_late_streak"] = streak
        if streak >= 2:
            inclusion_obj["inclusion_status"] = "EXCLUDED"
            document = db.documents.get(inclusion_obj.get("document_id"))
            if document is not None:
                docsvc.recompute_included_vendor_count(document)
                db.touch(document)
    else:
        inclusion_obj["_late_streak"] = 0
    db.touch(inclusion_obj)
    return ok(serialize(inclusion_obj), 200)


@bp.post("/research/vendor-inclusions/<inclusion_id>/fact-check-decisions")
def fact_check_decision(inclusion_id):
    authenticate(["ResearchDirector"])
    data = body()
    outcome = enum(require_str(data, "outcome"), FACT_CHECK_OUTCOMES, "outcome")
    inclusion_obj = require_inclusion(inclusion_id)

    if inclusion_obj.get("fact_check_status") != "VENDOR_RESPONDED":
        raise invalid_state("Only a VENDOR_RESPONDED inclusion can be adjudicated.")

    document = db.documents.get(inclusion_obj.get("document_id"))

    if outcome == "DISPUTE":
        if inclusion_obj.get("fact_check_round", 0) >= 3:
            raise invalid_state("The fact-check loop is capped at a round of 3.")
        inclusion_obj["fact_check_status"] = "DISPUTED"
        db.touch(inclusion_obj)
        docsvc.open_fact_check_round(inclusion_obj)
        db.touch(inclusion_obj)
        if document is not None:
            docsvc.recompute_fact_check_open_count(document)
            db.touch(document)
        return ok(serialize(inclusion_obj), 200)

    inclusion_obj["fact_check_status"] = "ADJUDICATED"
    db.touch(inclusion_obj)
    if document is None:
        return ok(serialize(inclusion_obj), 200)

    docsvc.recompute_fact_check_open_count(document)
    if (
        document.get("fact_check_open_count", 0) == 0
        and document.get("editorial_status") == "FACT_CHECK"
        and any(
            inc.get("inclusion_status") == "INCLUDED"
            for inc in docsvc.inclusions_of(document["id"])
        )
        and all(
            inc.get("fact_check_status") == "ADJUDICATED"
            for inc in docsvc.inclusions_of(document["id"])
            if inc.get("inclusion_status") == "INCLUDED"
        )
    ):
        document["editorial_status"] = "CLEARED"
        document["fact_check_open_count"] = 0
    db.touch(document)
    return ok(serialize(inclusion_obj), 200)


@bp.post("/research/vendor-inclusions/<inclusion_id>/reprint-copy-adjustments")
def reprint_copy_adjustment(inclusion_id):
    role, user_id = authenticate(["VendorRep", "PlatformAdmin"])
    data = body()
    delta = data.get("delta_copies")
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise bad_request("delta_copies must be an integer.")
    marketing_use = None
    if "permitted_marketing_use" in data and data.get("permitted_marketing_use") is not None:
        marketing_use = enum(
            data.get("permitted_marketing_use"), MARKETING_USES, "permitted_marketing_use"
        )
    inclusion_obj = require_inclusion(inclusion_id)
    _vendor_owns(role, user_id, inclusion_obj)

    used = inclusion_obj.get("reprint_copies_used", 0) + delta
    authorized = inclusion_obj.get("reprint_copies_authorized", 0)
    if used < 0 or used > authorized:
        raise ApiError(
            "ERR_REPRINT_COPIES_EXCEEDED",
            "The adjustment would drive reprint_copies_used outside its licensed range.",
            409,
        )

    inclusion_obj["reprint_copies_used"] = used
    if marketing_use is not None:
        inclusion_obj["permitted_marketing_use"] = marketing_use
    docsvc.refresh_reprint_fee(inclusion_obj)
    db.touch(inclusion_obj)
    return ok(serialize(inclusion_obj), 200)
