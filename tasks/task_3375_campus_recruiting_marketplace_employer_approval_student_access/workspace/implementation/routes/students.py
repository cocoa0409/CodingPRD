"""Student roster provisioning, profile maintenance, and outcome collection."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import (
    student_view,
    student_visible_to_employer,
    withdraw_student_cascade,
)
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("students", __name__)

WORK_AUTHORIZATIONS = ("US_CITIZEN", "PERMANENT_RESIDENT", "VISA_OPT_CPT", "SPONSORSHIP_REQUIRED")
PROFILE_VISIBILITIES = ("PUBLIC_TO_APPROVED_EMPLOYERS", "UNIVERSITY_ONLY", "HIDDEN")
STUDENT_STATUSES = ("ENROLLED", "ALUMNUS", "WITHDRAWN")
OUTCOME_STATUSES = ("UNREPORTED", "EMPLOYED", "GRAD_SCHOOL", "SEEKING", "OTHER")


@bp.route("/students", methods=["POST"])
def create_student():
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    body = Body()
    university_id = body.str_f("university_id", required=True)
    email = body.str_f("email", required=True)
    full_name = body.str_f("full_name", required=True)
    major = body.str_f("major", required=True)
    graduation_year = body.int_f("graduation_year", required=True, minv=1000, maxv=9999)
    work_authorization = body.str_f("work_authorization", required=True, enum=WORK_AUTHORIZATIONS)
    profile_visibility = body.str_f("profile_visibility", enum=PROFILE_VISIBILITIES)
    # Priority 3 ownership: the caller's university must own university_id.
    if university_id is not None and university_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may provision only its own roster")
    # Priority 4 existence.
    university = db.get("universities", university_id) if university_id else None
    if university_id is not None and university is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    # Priority 5 state: provisioning requires ONBOARDING or ACTIVE.
    if university is not None and university["status"] not in ("ONBOARDING", "ACTIVE"):
        fail("ERR_UNIVERSITY_NOT_PROVISIONABLE",
             "Student provisioning requires university status ONBOARDING or ACTIVE")
    body.finalize()
    if profile_visibility is None:
        profile_visibility = "UNIVERSITY_ONLY"
    record = {
        "id": db.new_id(),
        "university_id": university_id,
        "email": email,
        "full_name": full_name,
        "major": major,
        "graduation_year": graduation_year,
        "work_authorization": work_authorization,
        "profile_visibility": profile_visibility,
        "status": "ENROLLED",
        "outcome_status": "UNREPORTED",
        "outcome_employer_name": None,
        "outcome_recorded_at": None,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("students", record)
    return success_object(student_view(record), 201)


@bp.route("/students", methods=["GET"])
def list_students():
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "EmployerRecruiter", "PlatformAdmin")
    records = db.all_of("students")
    if role == "CareerCenterAdmin":
        records = [s for s in records if s["university_id"] == user_id]
    elif role == "EmployerRecruiter":
        records = [s for s in records if student_visible_to_employer(s, user_id)]
    f_university = request.args.get("university_id")
    f_major = request.args.get("major")
    f_grad_year = request.args.get("graduation_year")
    f_status = request.args.get("status")
    f_visible_for = request.args.get("visible_for_employer_id")
    if f_university is not None:
        records = [s for s in records if s["university_id"] == f_university]
    if f_major is not None:
        records = [s for s in records if s["major"] == f_major]
    if f_grad_year is not None:
        try:
            year = int(f_grad_year)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "graduation_year must be an integer")
        records = [s for s in records if s["graduation_year"] == year]
    if f_status is not None:
        records = [s for s in records if s["status"] == f_status]
    if f_visible_for is not None:
        records = [s for s in records if student_visible_to_employer(s, f_visible_for)]
    return paginate(records, student_view)


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "Student", "EmployerRecruiter", "PlatformAdmin")
    student = db.get("students", student_id)
    if student is None:
        fail("ERR_STUDENT_NOT_FOUND", "Student id does not exist")
    if role == "Student" and user_id != student["id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may read only their own record")
    if role == "CareerCenterAdmin" and user_id != student["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may read only its own students")
    if role == "EmployerRecruiter" and not student_visible_to_employer(student, user_id):
        fail("ERR_PROFILE_NOT_VISIBLE", "Student is not visible to this employer")
    return success_object(student_view(student))


@bp.route("/students/<student_id>", methods=["PATCH"])
def patch_student(student_id):
    user_id, role = get_context()
    require_role(role, "Student", "CareerCenterAdmin")
    body = Body()
    # Priority 2 per-target role rule: a Student may touch only profile_visibility.
    if role == "Student" and (
        body.has("status") or body.has("outcome_status") or body.has("outcome_employer_name")
    ):
        fail("ERR_UNAUTHORIZED_ROLE", "Student self-update may write profile_visibility only")
    student = db.get("students", student_id)
    if student is None:
        fail("ERR_STUDENT_NOT_FOUND", "Student id does not exist")
    if role == "Student" and user_id != student["id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may update only their own record")
    if role == "CareerCenterAdmin" and user_id != student["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may update only its own students")

    profile_visibility = body.str_f("profile_visibility", enum=PROFILE_VISIBILITIES)
    status_target = body.str_f("status", enum=STUDENT_STATUSES)
    outcome_status = body.str_f("outcome_status", enum=OUTCOME_STATUSES)
    has_outcome_employer = body.has("outcome_employer_name")
    outcome_employer_name = body.raw("outcome_employer_name")
    if has_outcome_employer and outcome_employer_name is not None and not isinstance(outcome_employer_name, str):
        body.bad = True

    # Priority 5 state: status transitions and outcome-write legality,
    # both evaluated against the pre-update status.
    if status_target is not None:
        legal = student["status"] == "ENROLLED" and status_target in ("ALUMNUS", "WITHDRAWN")
        if not legal:
            fail("ERR_INVALID_STUDENT_TRANSITION",
                 "Student status change %s -> %s is not allowed" % (student["status"], status_target))
    if (outcome_status is not None or has_outcome_employer) and student["status"] != "ALUMNUS":
        fail("ERR_OUTCOME_NOT_RECORDABLE", "Outcome fields are writable only while ALUMNUS")
    body.finalize()

    changed = False
    if profile_visibility is not None:
        student["profile_visibility"] = profile_visibility
        changed = True
    if status_target == "ALUMNUS":
        student["status"] = "ALUMNUS"
        changed = True
    if outcome_status is not None:
        if student["outcome_status"] == "UNREPORTED" and outcome_status != "UNREPORTED":
            student["outcome_recorded_at"] = now()
        student["outcome_status"] = outcome_status
        changed = True
    if has_outcome_employer:
        student["outcome_employer_name"] = outcome_employer_name
        changed = True
    withdraw = status_target == "WITHDRAWN"
    if withdraw:
        student["status"] = "WITHDRAWN"
        changed = True
    if changed:
        db.touch(student)
    if withdraw:
        withdraw_student_cascade(student)
    return success_object(student_view(student))
