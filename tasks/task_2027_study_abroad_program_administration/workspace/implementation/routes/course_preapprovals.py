"""Course pre-approval endpoints: create (OCC-guarded), list, review, revise."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role, check_student_ownership
from response import success_object, success_list
from utils import require_string, require_number, require_enum, require_int, parse_pagination, round_credit
from errors import not_found, invalid_request, invalid_state, ApiError, ERR_STALE_VERSION

bp = Blueprint("course_preapprovals", __name__)


def _conversion_factor_for_application(app):
    program = db.programs.get(app["program_id"])
    if not program:
        return None
    agreement = db.partner_agreements.get(program["partner_agreement_id"])
    if not agreement:
        return None
    return agreement["credit_conversion_factor"]


@bp.route("/api/v1/applications/<id>/course-preapprovals", methods=["POST"])
def create_course_preapproval(id):
    user_id, role = get_auth()
    require_role(role, ["Student"])

    app = db.applications.get(id)
    if not app:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, app["student_id"])

    body = request.get_json(silent=True) or {}
    course_code = require_string(body, "course_code")
    course_title = require_string(body, "course_title")
    host_credits = require_number(body, "host_credits")
    expected_application_version = require_int(body, "expected_application_version")

    if not (host_credits > 0):
        raise invalid_request("host_credits must be > 0")

    # OCC check (concurrency rule cpa-create-stale-application)
    if expected_application_version != app["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_application_version does not match the application's current version", 412)

    factor = _conversion_factor_for_application(app)
    home_credits_est = round_credit(host_credits, factor)

    # supersede existing PENDING/APPROVED records with same course_code for this application
    for rec in db.course_preapprovals.values():
        if (
            rec["application_id"] == app["id"]
            and rec["course_code"] == course_code
            and rec["status"] in ("PENDING", "APPROVED")
        ):
            rec["status"] = "SUPERSEDED"
            rec["version"] += 1
            rec["updated_at"] = now_iso()

    ts = now_iso()
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "course_code": course_code,
        "course_title": course_title,
        "host_credits": host_credits,
        "home_credits_est": home_credits_est,
        "status": "PENDING",
        "reviewed_by": None,
        "review_notes": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.course_preapprovals[rec["id"]] = rec

    # creation advances the parent application's version
    app["version"] += 1
    app["updated_at"] = now_iso()

    return success_object(rec, 201)


@bp.route("/api/v1/applications/<id>/course-preapprovals", methods=["GET"])
def list_course_preapprovals(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator", "FacultyApprover", "Student"])

    app = db.applications.get(id)
    if not app:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, app["student_id"])

    limit, offset = parse_pagination(request.args)
    items = [r for r in db.course_preapprovals.values() if r["application_id"] == app["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/api/v1/course-preapprovals/<id>/review", methods=["POST"])
def review(id):
    user_id, role = get_auth()
    require_role(role, ["FacultyApprover"])

    rec = db.course_preapprovals.get(id)
    if not rec:
        raise not_found("CoursePreApproval not found")

    body = request.get_json(silent=True) or {}
    decision = require_enum(body, "decision", {"APPROVED", "NEEDS_REVISION", "REJECTED"})

    if rec["status"] != "PENDING":
        raise invalid_state("CoursePreApproval is not in PENDING status")

    review_notes = body.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        raise invalid_request("review_notes must be a string or null")

    rec["status"] = decision
    rec["reviewed_by"] = user_id
    rec["review_notes"] = review_notes
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)


@bp.route("/api/v1/course-preapprovals/<id>/revise", methods=["POST"])
def revise(id):
    user_id, role = get_auth()
    require_role(role, ["Student"])

    rec = db.course_preapprovals.get(id)
    if not rec:
        raise not_found("CoursePreApproval not found")

    app = db.applications.get(rec["application_id"])
    if not app:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, app["student_id"])

    body = request.get_json(silent=True) or {}
    host_credits = require_number(body, "host_credits")
    if not (host_credits > 0):
        raise invalid_request("host_credits must be > 0")

    course_title = body.get("course_title")
    if course_title is not None and not isinstance(course_title, str):
        raise invalid_request("course_title must be a string")

    if rec["status"] != "NEEDS_REVISION":
        raise invalid_state("CoursePreApproval is not in NEEDS_REVISION status")

    factor = _conversion_factor_for_application(app)
    rec["host_credits"] = host_credits
    if course_title is not None:
        rec["course_title"] = course_title
    rec["home_credits_est"] = round_credit(host_credits, factor)
    rec["status"] = "PENDING"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)
