"""ConditionAssessment endpoints: create/list/get, submit, accept, reject."""
from flask import Blueprint

import db
from calculations import recompute_estimates
from errors import ApiError
from middleware import current_user, require_roles
from models import new_assessment, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from util import ALL_ROLES

bp = Blueprint("assessments", __name__)


def get_assessment_or_404(assessment_id):
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ConditionAssessment not found")
    return assessment


@bp.route("/acquisitions/targets/<target_id>/assessments", methods=["POST"])
def create_assessment(target_id):
    user_id, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    target = get_target_or_404(target_id)
    body = json_body()
    notes = body.get("notes", "")
    if not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "notes must be a string")
    assessment = new_assessment(target["id"], notes, user_id)
    return success_obj(assessment, status=201)


@bp.route("/acquisitions/targets/<target_id>/assessments", methods=["GET"])
def list_assessments(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.assessments_of_target(target_id),
                     key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_assessment_or_404(assessment_id))


@bp.route("/acquisitions/assessments/<assessment_id>/submit", methods=["POST"])
def submit_assessment(assessment_id):
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    assessment = get_assessment_or_404(assessment_id)
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not in DRAFT")
    items = [i for i in db.capital_items_of_assessment(assessment_id)
             if i["status"] != "SPLIT"]
    if not items:
        raise ApiError("ERR_ASSESSMENT_EMPTY", 409, "Assessment has no non-SPLIT capital items")
    recompute_estimates(assessment)
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return success_obj(assessment)


@bp.route("/acquisitions/assessments/<assessment_id>/accept", methods=["POST"])
def accept_assessment(assessment_id):
    user_id, role = current_user()
    require_roles(role, ["EngineeringReviewer"])
    assessment = get_assessment_or_404(assessment_id)
    # Priority 4: segregation of duties before the state check.
    if user_id == assessment["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTY", 403,
                       "Acceptor must not be the assessment creator")
    if assessment["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not in SUBMITTED")
    target = db.targets[assessment["target_id"]]
    if target["status"] not in ("SCREENING", "VALUATION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Target is not in SCREENING or VALUATION")
    # Supersede any previously ACCEPTED assessment of this target.
    for other in db.assessments_of_target(target["id"]):
        if other["id"] != assessment["id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    assessment["status"] = "ACCEPTED"
    touch(assessment)
    if target["status"] == "SCREENING":
        target["status"] = "VALUATION"
        target["filing_estimate_cents"] = assessment["filing_estimate_cents"]
        touch(target)
    return success_obj(assessment)


@bp.route("/acquisitions/assessments/<assessment_id>/reject", methods=["POST"])
def reject_assessment(assessment_id):
    user_id, role = current_user()
    require_roles(role, ["EngineeringReviewer"])
    assessment = get_assessment_or_404(assessment_id)
    if user_id == assessment["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTY", 403,
                       "Rejector must not be the assessment creator")
    if assessment["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not in SUBMITTED")
    assessment["status"] = "DRAFT"
    assessment["revision_count"] += 1
    touch(assessment)
    return success_obj(assessment)
