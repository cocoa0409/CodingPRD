"""Training courses and enrollments."""
from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, not_found
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, parse_date, stamp_common, touch,
    parse_pagination,
)

bp = Blueprint("training", __name__)


@bp.post("/program/training-courses")
def create_course():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["title", "credits", "validity_months"])
    title = require_string(data, "title")
    credits = data["credits"]
    if not isinstance(credits, int) or isinstance(credits, bool) or credits < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "credits must be a non-negative integer")
    vm = data["validity_months"]
    if not isinstance(vm, int) or isinstance(vm, bool) or vm < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "validity_months must be a non-negative integer")
    with db.lock:
        course = stamp_common({
            "title": title,
            "credits": credits,
            "validity_months": vm,
        })
        db.training_courses[course["id"]] = course
    return success(course, status=201)


@bp.post("/program/training-enrollments")
def create_enrollment():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["contractor_id", "course_id"])
    contractor_id = require_string(data, "contractor_id")
    course_id = require_string(data, "course_id")
    with db.lock:
        if contractor_id not in db.contractors:
            raise not_found("Contractor")
        if course_id not in db.training_courses:
            raise not_found("TrainingCourse")
        en = stamp_common({
            "contractor_id": contractor_id,
            "course_id": course_id,
            "status": "ENROLLED",
            "completed_at": None,
        })
        db.training_enrollments[en["id"]] = en
    return success(en, status=201)


@bp.get("/program/training-enrollments/<eid>")
def get_enrollment(eid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        en = db.training_enrollments.get(eid)
        if en is None:
            raise not_found("TrainingEnrollment")
    return success(en)


@bp.get("/program/training-enrollments")
def list_enrollments():
    require_roles("ProgramAdmin", "Contractor")
    limit, offset = parse_pagination()
    contractor_id = request.args.get("contractor_id")
    course_id = request.args.get("course_id")
    status = request.args.get("status")
    if status is not None and status not in ("ENROLLED", "COMPLETED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter")
    with db.lock:
        rows = list(db.training_enrollments.values())
        if contractor_id is not None:
            rows = [r for r in rows if r["contractor_id"] == contractor_id]
        if course_id is not None:
            rows = [r for r in rows if r["course_id"] == course_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda x: x["created_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.post("/program/training-enrollments/<eid>/complete")
def complete_enrollment(eid):
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["completed_at"])
    completed_at = require_string(data, "completed_at")
    parse_date(completed_at)
    with db.lock:
        en = db.training_enrollments.get(eid)
        if en is None:
            raise not_found("TrainingEnrollment")
        if en["status"] != "ENROLLED":
            raise ApiError(ERR_INVALID_STATE, 409, "Enrollment is not ENROLLED")
        en["status"] = "COMPLETED"
        en["completed_at"] = completed_at
        touch(en)
    return success(en)
