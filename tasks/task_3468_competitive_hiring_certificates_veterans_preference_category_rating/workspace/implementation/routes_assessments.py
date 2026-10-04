"""SME assessment endpoints (PRD 3.5): create DRAFT, submit/resubmit,
accept (cascades application QUALIFIED -> RATED), return."""
from flask import Blueprint

from auth import get_auth, require_roles
from calc import category_for_score, sme_technical_score
from envelope import success_object
from errors import fail, forbidden, invalid_state, not_found
from serializers import assessment_out
from store import DB, base_fields, now, touch
from validate import get_body, opt_int, req_int

bp = Blueprint("assessments", __name__)


def get_assessment_or_404(assessment_id):
    row = DB.assessments.get(assessment_id)
    if row is None:
        not_found("assessment")
    return row


@bp.route("/hiring/applications/<application_id>/assessments", methods=["POST"])
def create_assessment(application_id):
    user_id, role = get_auth()
    require_roles(role, ["SME"])
    body = get_body()
    r_k = req_int(body, "rating_knowledge", 1, 5)
    r_s = req_int(body, "rating_skill", 1, 5)
    r_a = req_int(body, "rating_ability", 1, 5)
    app_row = DB.applications.get(application_id)
    if app_row is None:
        not_found("application")
    if app_row["status"] != "QUALIFIED":
        fail("ERR_APPLICATION_WRONG_STATE", "application is not QUALIFIED")
    for a in DB.assessments.values():
        if a["application_id"] == app_row["id"] and a["status"] in ("DRAFT", "SUBMITTED"):
            fail("ERR_ACTIVE_ASSESSMENT_EXISTS",
                 "an assessment is already active for this application")
    ann = DB.announcements[app_row["announcement_id"]]
    if ann["assessment_method"] != "CATEGORY_RATING":
        fail("ERR_ASSESSMENT_NOT_APPLICABLE",
             "assessments exist only for CATEGORY_RATING announcements")
    row = base_fields()
    row.update({
        "application_id": app_row["id"], "sme_user_id": user_id,
        "rating_knowledge": r_k, "rating_skill": r_s, "rating_ability": r_a,
        "technical_score": None, "quality_category": None,
        "return_reason": None, "status": "DRAFT",
    })
    DB.assessments[row["id"]] = row
    return success_object(assessment_out(row), 201)


@bp.route("/hiring/assessments/<assessment_id>", methods=["GET"])
def read_assessment(assessment_id):
    _, role = get_auth()
    require_roles(role, ["SME", "HRSpecialist"])
    row = get_assessment_or_404(assessment_id)
    return success_object(assessment_out(row))


@bp.route("/hiring/assessments/<assessment_id>/submit", methods=["POST"])
def submit_assessment(assessment_id):
    user_id, role = get_auth()
    require_roles(role, ["SME"])
    body = get_body()
    new_k = opt_int(body, "rating_knowledge", 1, 5)
    new_s = opt_int(body, "rating_skill", 1, 5)
    new_a = opt_int(body, "rating_ability", 1, 5)
    row = get_assessment_or_404(assessment_id)
    if user_id != row["sme_user_id"]:
        forbidden("SME may submit only assessments it authored")
    if row["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_ASSESSMENT_NOT_SUBMITTED",
             "submit requires DRAFT or RETURNED state")
    if new_k is not None:
        row["rating_knowledge"] = new_k
    if new_s is not None:
        row["rating_skill"] = new_s
    if new_a is not None:
        row["rating_ability"] = new_a
    score = sme_technical_score(row["rating_knowledge"], row["rating_skill"], row["rating_ability"])
    app_row = DB.applications[row["application_id"]]
    ann = DB.announcements[app_row["announcement_id"]]
    row["technical_score"] = score
    row["quality_category"] = category_for_score(score, ann["bq_cut"], ann["wq_cut"])
    row["status"] = "SUBMITTED"
    touch(row)
    return success_object(assessment_out(row))


@bp.route("/hiring/assessments/<assessment_id>/accept", methods=["POST"])
def accept_assessment(assessment_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    get_body()
    row = get_assessment_or_404(assessment_id)
    if row["status"] != "SUBMITTED":
        fail("ERR_ASSESSMENT_NOT_SUBMITTED", "assessment is not SUBMITTED")
    app_row = DB.applications[row["application_id"]]
    if app_row["status"] != "QUALIFIED":
        invalid_state("application is not QUALIFIED")
    for a in DB.assessments.values():
        if a["application_id"] == app_row["id"] and a["id"] != row["id"] and a["status"] == "ACCEPTED":
            fail("ERR_ACTIVE_ASSESSMENT_EXISTS",
                 "another ACCEPTED assessment exists for this application")
    row["status"] = "ACCEPTED"
    touch(row)
    # Cascade: application QUALIFIED -> RATED with score/category copied.
    app_row["technical_score"] = row["technical_score"]
    app_row["quality_category"] = row["quality_category"]
    app_row["status"] = "RATED"
    app_row["notified_at"] = now()
    touch(app_row)
    return success_object(assessment_out(row))


@bp.route("/hiring/assessments/<assessment_id>/return", methods=["POST"])
def return_assessment(assessment_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    body = get_body()
    row = get_assessment_or_404(assessment_id)
    if row["status"] != "SUBMITTED":
        fail("ERR_ASSESSMENT_NOT_SUBMITTED", "assessment is not SUBMITTED")
    reason = body.get("return_reason")
    if reason is not None and not isinstance(reason, str):
        fail("ERR_INVALID_REQUEST", "return_reason must be a string")
    row["return_reason"] = reason
    row["status"] = "RETURNED"
    touch(row)
    return success_object(assessment_out(row))
