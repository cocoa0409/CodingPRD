"""Hardship packages and seller documentation (PRD §3.1 - §3.3)."""
from flask import Blueprint

import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, success
from errors import fail
from serializers import document_out, package_out
from timeutil import elapsed_days

bp = Blueprint("packages", __name__)

PACKAGE_READ_ROLES = (K.ROLE_NEGOTIATOR, K.ROLE_SERVICER_ANALYST, K.ROLE_PLATFORM_ADMIN)


# ---------------------------------------------------------------------------
# hardship packages
# ---------------------------------------------------------------------------
@bp.post("/short-sale/cases/<case_id>/hardship-packages")
def create_package(case_id):
    user_id = require(K.ROLE_NEGOTIATOR)
    case = S.need_case(case_id)
    data = V.body()
    package = {
        "id": db.new_id(),
        "case_id": case["id"],
        "hardship_reason": V.req_enum(data, "hardship_reason", K.HARDSHIP_REASONS),
        "monthly_income_cents": V.req_int(data, "monthly_income_cents", minimum=1),
        "monthly_expenses_cents": V.req_int(data, "monthly_expenses_cents", minimum=1),
        "liquid_assets_cents": V.req_int(data, "liquid_assets_cents", minimum=0),
        "assembled_by_user_id": user_id,
        "document_count": 0,
        "pending_document_count": 0,
        "verified_document_count": 0,
        "rejected_document_count": 0,
        "hardship_score_intake": None,
        "hardship_score_audit": None,
        "status": "DRAFT",
    }
    S.require_case_actionable(case)
    if S.case_package(case["id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "This case already carries a hardship package.")
    db.insert("packages", package)
    return created(package_out(package))


@bp.get("/short-sale/hardship-packages/<package_id>")
def get_package(package_id):
    require(*PACKAGE_READ_ROLES)
    package = S.need_package(package_id)
    return success(package_out(package))


@bp.get("/short-sale/cases/<case_id>/hardship-packages")
def list_case_packages(case_id):
    require(*PACKAGE_READ_ROLES)
    case = S.need_case(case_id)
    return collection(S.case_packages(case["id"]), package_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/hardship-packages/<package_id>/submit")
def submit_package(package_id):
    require(K.ROLE_NEGOTIATOR)
    package = S.need_package(package_id)
    V.body()
    case = db.get("cases", package["case_id"])

    # rung 9 — state admissibility
    if package["status"] not in ("DRAFT", "REVALIDATION_REQUIRED"):
        fail(
            "ERR_PACKAGE_NOT_ACTIONABLE",
            "A package in %s may not be submitted." % package["status"],
        )
    from_state = package["status"]

    # rung 13 — required documentation
    if not S.required_kinds_present(package):
        fail(
            "ERR_REQUIRED_DOCUMENT_MISSING",
            "Every required document type must be filed before submission.",
        )

    package["hardship_score_intake"] = S.score_package(package, "INTAKE")
    package["status"] = "SUBMITTED"

    if from_state == "DRAFT":
        if case["negotiation_status"] == "INTAKE":
            case["negotiation_status"] = "PACKAGE_REVIEW"
    else:  # REVALIDATION_REQUIRED
        if case["documentation_status"] == "DOC_STALE":
            case["documentation_status"] = "DOC_PENDING"

    return success(package_out(package))


@bp.post("/short-sale/hardship-packages/<package_id>/decision")
def decide_package(package_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    package = S.need_package(package_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", K.PACKAGE_DECISION_OUTCOMES)
    case = db.get("cases", package["case_id"])

    # rung 9 — state admissibility
    if package["status"] != "SUBMITTED":
        fail(
            "ERR_PACKAGE_NOT_ACTIONABLE",
            "A package in %s may not be decided." % package["status"],
        )

    # The audit score is stamped BEFORE the outcome is evaluated, so it is
    # persisted even when the decision that follows fails.
    package["hardship_score_audit"] = S.score_package(package, "SERVICER_AUDIT")

    if outcome == "ACCEPT":
        # rung 27 — hardship score floor
        if package["hardship_score_audit"] < K.HARDSHIP_MIN_SCORE:
            fail(
                "ERR_HARDSHIP_SCORE_BELOW_MINIMUM",
                "The servicer-audit hardship score is below the minimum.",
            )
        package["status"] = "ACCEPTED"
        if case["negotiation_status"] == "PACKAGE_REVIEW":
            case["negotiation_status"] = "MARKETED"
    else:
        package["status"] = "REJECTED"
        if case["negotiation_status"] == "PACKAGE_REVIEW":
            case["negotiation_status"] = "DECLINED"

    return success(package_out(package))


# ---------------------------------------------------------------------------
# seller documents
# ---------------------------------------------------------------------------
@bp.post("/short-sale/hardship-packages/<package_id>/documents")
def create_document(package_id):
    require(K.ROLE_NEGOTIATOR)
    package = S.need_package(package_id)
    data = V.body()
    document = {
        "id": db.new_id(),
        "package_id": package["id"],
        "doc_type": V.req_enum(data, "doc_type", K.DOC_TYPES),
        "issued_on": V.req_datetime(data, "issued_on"),
        "reference_label": V.req_string(data, "reference_label"),
        "age_days_at_review": None,
        "reviewed_by_user_id": None,
        "status": "PENDING",
    }
    db.insert("documents", document)
    package["document_count"] += 1
    package["pending_document_count"] += 1
    return created(document_out(document))


@bp.get("/short-sale/hardship-packages/<package_id>/documents")
def list_documents(package_id):
    require(*PACKAGE_READ_ROLES)
    package = S.need_package(package_id)
    doc_type = enum_filter("doc_type", K.DOC_TYPES)
    status = enum_filter("status", K.DOCUMENT_STATUSES)
    rows = S.package_documents(package["id"])
    if doc_type is not None:
        rows = [r for r in rows if r["doc_type"] == doc_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, document_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/documents/<document_id>/review")
def review_document(document_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    document = S.need_document(document_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", K.DOCUMENT_REVIEW_OUTCOMES)
    V.opt_string(data, "note")

    package = db.get("packages", document["package_id"])
    case = db.get("cases", package["case_id"])

    # rung 9 — state admissibility
    if package["status"] == "REJECTED":
        fail(
            "ERR_DOCUMENT_NOT_REVIEWABLE",
            "No review is permitted while the owning package is rejected.",
        )
    if outcome in ("VERIFY", "REJECT") and document["status"] != "PENDING":
        fail("ERR_DOCUMENT_NOT_REVIEWABLE", "Only a PENDING document may be verified or rejected.")
    if outcome == "REVOKE" and document["status"] != "VERIFIED":
        fail("ERR_DOCUMENT_NOT_REVIEWABLE", "Only a VERIFIED document may be revoked.")

    age = elapsed_days(document["issued_on"], db.now())

    # rung 14 — document freshness
    if outcome == "VERIFY" and age > K.DOCUMENT_MAX_AGE_DAYS:
        fail("ERR_DOCUMENT_EXPIRED", "The document is too old to be verified.")

    document["age_days_at_review"] = age
    document["reviewed_by_user_id"] = user_id

    if outcome == "VERIFY":
        document["status"] = "VERIFIED"
        package["verified_document_count"] += 1
        package["pending_document_count"] -= 1
        if case["documentation_status"] == "DOC_PENDING" and S.required_kinds_verified(package):
            case["documentation_status"] = "DOC_COMPLETE"
    elif outcome == "REJECT":
        document["status"] = "REJECTED"
        package["rejected_document_count"] += 1
        package["pending_document_count"] -= 1
    else:  # REVOKE — the compensating action for a verification
        document["status"] = "PENDING"
        package["verified_document_count"] -= 1
        package["pending_document_count"] += 1
        if case["documentation_status"] == "DOC_COMPLETE" and not S.required_kinds_verified(package):
            case["documentation_status"] = "DOC_PENDING"

    return success(document_out(document))
