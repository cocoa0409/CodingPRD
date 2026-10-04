"""Routes: scholarship applications and adjudication."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, success_object, paginate, get_body,
    require_fields, today,
)
from services import (
    recompute_branch, reprice_pending_drafts, compute_income_ratio,
    award_pct_for_ratio, association_for_branch, DOC_KINDS,
)

bp = Blueprint("scholarships", __name__)

APPLICATION_FIELDS = [
    "id", "branch_id", "membership_id", "applicant_member_id", "household_size",
    "annual_income_cents", "documentation", "income_ratio", "preview_award_pct",
    "award_pct", "award_obligation_cents", "status", "award_start_on",
    "award_end_on", "renews_application_id", "created_at", "updated_at", "version",
]


def serialize_application(a):
    out = db.serialize(a, APPLICATION_FIELDS)
    if a.get("income_ratio") is not None:
        out["income_ratio"] = float(a["income_ratio"])
    return out


def _validate_documentation(documentation):
    docs = documentation or []
    if not isinstance(docs, list) or not docs:
        raise ApiError("ERR_DOCUMENTATION_MISSING",
                       "At least one documentation kind is required")
    if not any(d in DOC_KINDS for d in docs):
        raise ApiError("ERR_DOCUMENTATION_MISSING",
                       "documentation must include TAX_RETURN, PAY_STUB, or BENEFITS_LETTER")


def _compute_preview(app):
    branch = db.STORES["branches"].get(app["branch_id"])
    assoc = association_for_branch(branch) if branch else None
    if assoc is None:
        app["income_ratio"] = None
        app["preview_award_pct"] = None
        return
    ratio = compute_income_ratio(
        app["annual_income_cents"], app["household_size"], assoc["ami_base_cents"])
    app["income_ratio"] = ratio
    app["preview_award_pct"] = award_pct_for_ratio(ratio)


@bp.route("/scholarship-applications", methods=["POST"])
def create_application():
    role, user_id = auth()
    require_role(role, ["Member", "FrontDesk", "BranchDirector"])
    body = get_body()
    require_fields(body, ["branch_id", "membership_id", "applicant_member_id",
                          "household_size", "annual_income_cents", "documentation"])
    branch = db.STORES["branches"].get(body["branch_id"])
    if branch is None:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    membership = db.STORES["memberships"].get(body["membership_id"])
    if membership is None:
        raise ApiError("ERR_NOT_FOUND", f"Membership {body['membership_id']} not found")
    if body["applicant_member_id"] not in db.STORES["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "Applicant member not found")
    if role == "Member" and user_id != body["applicant_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "Only the applicant may file their application")
    renews_id = body.get("renews_application_id")
    if renews_id is not None and renews_id not in db.STORES["applications"]:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "renews_application_id not found")
    hs = body["household_size"]
    if not isinstance(hs, int) or hs < 1 or hs > 12:
        raise ApiError("ERR_INVALID_REQUEST", "household_size must be an integer 1..12")
    _validate_documentation(body["documentation"])
    rec = db.new_record("applications", {
        "branch_id": branch["id"],
        "membership_id": membership["id"],
        "applicant_member_id": body["applicant_member_id"],
        "household_size": hs,
        "annual_income_cents": body["annual_income_cents"],
        "documentation": list(body["documentation"]),
        "income_ratio": None,
        "preview_award_pct": None,
        "award_pct": None,
        "award_obligation_cents": 0,
        "status": "SUBMITTED",
        "award_start_on": None,
        "award_end_on": None,
        "renews_application_id": renews_id,
    })
    _compute_preview(rec)
    return success_object(serialize_application(rec), 201)


@bp.route("/scholarship-applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "Member"])
    rec = db.get("applications", applicationId)
    return success_object(serialize_application(rec))


@bp.route("/scholarship-applications", methods=["GET"])
def list_applications():
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "Member"])
    items = db.all_records("applications")
    branch_id = request.args.get("branch_id")
    membership_id = request.args.get("membership_id")
    applicant_member_id = request.args.get("applicant_member_id")
    status = request.args.get("status")
    renews_application_id = request.args.get("renews_application_id")
    if branch_id:
        items = [a for a in items if a["branch_id"] == branch_id]
    if membership_id:
        items = [a for a in items if a["membership_id"] == membership_id]
    if applicant_member_id:
        items = [a for a in items if a["applicant_member_id"] == applicant_member_id]
    if status:
        items = [a for a in items if a["status"] == status]
    if renews_application_id:
        items = [a for a in items if a.get("renews_application_id") == renews_application_id]
    return paginate([serialize_application(a) for a in items])


# ---------------------------------------------------------------------------
# Application state transitions
# ---------------------------------------------------------------------------

@bp.route("/scholarship-applications/<applicationId>/review", methods=["POST"])
def review_application(applicationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("applications", applicationId)
    if rec["status"] in ("APPROVED", "DENIED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Application is terminal")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only SUBMITTED applications can be reviewed")
    rec["status"] = "UNDER_REVIEW"
    db.touch(rec, bump=False)
    return success_object(serialize_application(rec))


@bp.route("/scholarship-applications/<applicationId>/request-info", methods=["POST"])
def request_info(applicationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("applications", applicationId)
    if rec["status"] in ("APPROVED", "DENIED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Application is terminal")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW applications can request info")
    rec["status"] = "MORE_INFO_REQUIRED"
    db.touch(rec, bump=False)
    return success_object(serialize_application(rec))


@bp.route("/scholarship-applications/<applicationId>/submit-info", methods=["POST"])
def submit_info(applicationId):
    role, user_id = auth()
    require_role(role, ["Member"])
    rec = db.get("applications", applicationId)
    if user_id != rec["applicant_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "Only the applicant may resubmit documentation")
    if rec["status"] in ("APPROVED", "DENIED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Application is terminal")
    if rec["status"] != "MORE_INFO_REQUIRED":
        raise ApiError("ERR_INVALID_STATE", "Application is not awaiting information")
    body = get_body()
    require_fields(body, ["documentation"])
    _validate_documentation(body["documentation"])
    rec["documentation"] = list(body["documentation"])
    if "annual_income_cents" in body:
        rec["annual_income_cents"] = body["annual_income_cents"]
    if "household_size" in body:
        hs = body["household_size"]
        if not isinstance(hs, int) or hs < 1 or hs > 12:
            raise ApiError("ERR_INVALID_REQUEST", "household_size must be an integer 1..12")
        rec["household_size"] = hs
    rec["status"] = "UNDER_REVIEW"
    _compute_preview(rec)
    db.touch(rec, bump=False)
    return success_object(serialize_application(rec))


@bp.route("/scholarship-applications/<applicationId>/approve", methods=["POST"])
def approve_application(applicationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("applications", applicationId)
    if rec["status"] in ("APPROVED", "DENIED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Application is terminal")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW applications can be approved")
    body = get_body()
    membership = db.STORES["memberships"].get(rec["membership_id"])
    if membership is None:
        raise ApiError("ERR_NOT_FOUND", "Membership not found")
    branch = db.STORES["branches"].get(rec["branch_id"])
    recompute_branch(branch)
    # capacity/uniqueness: one APPROVED award per membership
    for other in db.STORES["applications"].values():
        if (other["id"] != rec["id"] and other["membership_id"] == membership["id"]
                and other["status"] == "APPROVED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_AWARD",
                           "Membership already has an APPROVED award")
    # fiscal: eligibility then pool solvency
    assoc = association_for_branch(branch)
    ratio = compute_income_ratio(
        rec["annual_income_cents"], rec["household_size"], assoc["ami_base_cents"])
    award = award_pct_for_ratio(ratio)
    if award is None:
        raise ApiError("ERR_AWARD_INELIGIBLE", "income_ratio >= 0.80; must deny instead")
    category = db.STORES["categories"].get(membership["category_id"])
    from decimal import Decimal
    from common import round_cents
    obligation = round_cents(Decimal(12) * Decimal(category["monthly_dues_cents"]) * Decimal(str(award)))
    if branch["scholarship_pool_available_cents"] < obligation:
        raise ApiError("ERR_POOL_EXHAUSTED", "Branch scholarship pool is exhausted")
    # OCC last
    expected = body.get("expected_membership_version")
    if expected is not None and expected != membership["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_membership_version does not match")
    start = today()
    rec["income_ratio"] = ratio
    rec["award_pct"] = award
    rec["award_obligation_cents"] = obligation
    rec["status"] = "APPROVED"
    rec["award_start_on"] = start.isoformat()
    rec["award_end_on"] = (start + timedelta(days=365)).isoformat()
    db.touch(rec, bump=False)
    membership["assistance_pct"] = award
    db.touch(membership, bump=True)  # award approval increments the membership version
    reprice_pending_drafts(membership)
    recompute_branch(branch)
    return success_object(serialize_application(rec))


@bp.route("/scholarship-applications/<applicationId>/deny", methods=["POST"])
def deny_application(applicationId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("applications", applicationId)
    if rec["status"] in ("APPROVED", "DENIED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "Application is terminal")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW applications can be denied")
    rec["status"] = "DENIED"
    db.touch(rec, bump=False)
    return success_object(serialize_application(rec))
